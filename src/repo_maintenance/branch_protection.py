"""Require pull requests on the default branch, overridable by repo admins.

Done with a repository ruleset. If the default branch is already covered by
one ruleset, it's replaced with ours; if by more than one, or by classic
branch protection, we refuse to touch it.
"""

import difflib
import json
from typing import Annotated, Literal

import pydantic

from repo_maintenance import github, plan

# Models we compare against our desired state forbid extra fields, so that a
# setting we don't know about can't make us think a repo is in sync when it
# isn't.


class Strict(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)


class RefNameCondition(Strict):
    include: list[str]
    exclude: list[str]


class Conditions(Strict):
    ref_name: RefNameCondition


class BypassActor(Strict):
    actor_id: int | None
    actor_type: Literal[
        "Integration",
        "OrganizationAdmin",
        "RepositoryRole",
        "Team",
        "DeployKey",
        "User",
    ]
    bypass_mode: Literal["always", "pull_request", "exempt"]


class DeletionRule(Strict):
    type: Literal["deletion"] = "deletion"


class NonFastForwardRule(Strict):
    type: Literal["non_fast_forward"] = "non_fast_forward"


class PullRequestParameters(Strict):
    required_approving_review_count: int
    dismiss_stale_reviews_on_push: bool
    required_reviewers: list[pydantic.JsonValue]
    require_code_owner_review: bool
    require_last_push_approval: bool
    required_review_thread_resolution: bool
    require_extra_approval_for_unattributed_changes: bool
    allowed_merge_methods: list[Literal["merge", "squash", "rebase"]]


class PullRequestRule(Strict):
    type: Literal["pull_request"] = "pull_request"
    parameters: PullRequestParameters


class OtherRule(pydantic.BaseModel):
    """Any rule we don't have a model for, or that has fields we don't know.

    Keeps all its fields, so that it still shows up properly in diffs.
    """

    model_config = pydantic.ConfigDict(extra="allow", frozen=True)
    type: str


type Rule = Annotated[
    DeletionRule | NonFastForwardRule | PullRequestRule | OtherRule,
    # Try the specific models first, so OtherRule is only a fallback.
    pydantic.Field(union_mode="left_to_right"),
]


class Ruleset(pydantic.BaseModel):
    """A ruleset as we create it, and the parts of an existing one we compare.

    Responses also include id, timestamps, links etc., which we ignore.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    name: str
    target: Literal["branch", "tag", "push"]
    enforcement: Literal["active", "evaluate", "disabled"]
    conditions: Conditions
    rules: list[Rule]
    # Only visible to admins: for anyone else GitHub returns null, so a
    # validation error here probably means you aren't authenticated as one.
    bypass_actors: list[BypassActor]


class ActiveRule(pydantic.BaseModel):
    """An entry in GET /repos/{repo}/rules/branches/{branch}."""

    type: str
    ruleset_id: int


# The REST docs (https://docs.github.com/en/rest/repos/rules) only say
# actor_id is "the ID of the actor that can bypass a ruleset", without listing
# the IDs of the built-in repository roles. 5 for admin is folklore; to check
# it, look for a "Repository admin" bypass in the UI of a ruleset this created.
REPOSITORY_ADMIN_ROLE_ID = 5

DESIRED = Ruleset(
    name="default",
    target="branch",
    enforcement="active",
    conditions=Conditions(
        ref_name=RefNameCondition(include=["~DEFAULT_BRANCH"], exclude=[]),
    ),
    rules=[
        DeletionRule(),
        NonFastForwardRule(),
        PullRequestRule(
            parameters=PullRequestParameters(
                required_approving_review_count=1,
                dismiss_stale_reviews_on_push=True,
                required_reviewers=[],
                require_code_owner_review=False,
                require_last_push_approval=True,
                required_review_thread_resolution=False,
                require_extra_approval_for_unattributed_changes=False,
                allowed_merge_methods=["merge", "squash", "rebase"],
            ),
        ),
    ],
    bypass_actors=[
        BypassActor(
            actor_id=REPOSITORY_ADMIN_ROLE_ID,
            actor_type="RepositoryRole",
            bypass_mode="always",
        ),
    ],
)


def _canonical_json(ruleset: Ruleset) -> str:
    data = ruleset.model_dump(mode="json")
    data["rules"].sort(key=lambda rule: rule["type"])
    data["bypass_actors"].sort(key=lambda actor: json.dumps(actor, sort_keys=True))
    return json.dumps(data, indent=2, sort_keys=True)


def step(repo: plan.Repository) -> list[plan.Change]:
    branch = repo.default_branch
    try:
        github.request("GET", f"/repos/{repo.full_name}/branches/{branch}/protection")
    except github.NotFound:
        pass
    else:
        raise plan.CannotPlan(
            f"{branch} has classic branch protection;"
            " remove it (or convert it to a ruleset) by hand first"
        )

    active_rules = pydantic.TypeAdapter(list[ActiveRule]).validate_json(
        github.request("GET", f"/repos/{repo.full_name}/rules/branches/{branch}")
    )
    ruleset_ids = sorted({rule.ruleset_id for rule in active_rules})
    want = _canonical_json(DESIRED)
    body = DESIRED.model_dump(mode="json")

    match ruleset_ids:
        case []:
            return [
                plan.Change(
                    description=f"create ruleset {DESIRED.name!r}",
                    detail=want,
                    action=plan.ApiCall(
                        method="POST", path=f"/repos/{repo.full_name}/rulesets", body=body
                    ),
                )
            ]
        case [ruleset_id]:
            path = f"/repos/{repo.full_name}/rulesets/{ruleset_id}"
            existing = Ruleset.model_validate_json(github.request("GET", path))
            have = _canonical_json(existing)
            if have == want:
                return []
            diff = difflib.unified_diff(
                have.splitlines(),
                want.splitlines(),
                fromfile=f"ruleset {ruleset_id} (current)",
                tofile=f"ruleset {ruleset_id} (desired)",
                lineterm="",
            )
            return [
                plan.Change(
                    description=f"update ruleset {ruleset_id} ({existing.name!r})",
                    detail="\n".join(diff),
                    action=plan.ApiCall(method="PUT", path=path, body=body),
                )
            ]
        case _:
            raise plan.CannotPlan(
                f"{branch} is covered by multiple rulesets {ruleset_ids}; not touching it"
            )
