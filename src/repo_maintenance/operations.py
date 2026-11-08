"""Each step inspects a repo and returns the changes needed to bring it in line."""

import dataclasses
import difflib
import json
from collections.abc import Callable

import pydantic

from repo_maintenance import gh, models


@dataclasses.dataclass(frozen=True, kw_only=True)
class Change:
    description: str
    detail: str = ""
    apply: Callable[[], None]


type Step = Callable[[models.Repository], list[Change]]


# quality-of-life

QUALITY_OF_LIFE = models.RepositorySettings(delete_branch_on_merge=True)


def quality_of_life(repo: models.Repository) -> list[Change]:
    have = models.RepositorySettings.model_validate(repo, from_attributes=True)
    want_fields = QUALITY_OF_LIFE.model_dump()
    have_fields = have.model_dump()
    patch = {k: v for k, v in want_fields.items() if have_fields[k] != v}
    if not patch:
        return []
    return [
        Change(
            description="update repository settings",
            detail="\n".join(f"{k}: {have_fields[k]!r} -> {v!r}" for k, v in patch.items()),
            apply=lambda: gh.send("PATCH", f"/repos/{repo.full_name}", body=json.dumps(patch)),
        )
    ]


# branch-protection

REPOSITORY_ADMIN_ROLE_ID = 5

DEFAULT_BRANCH_RULESET = models.Ruleset(
    name="default",
    target="branch",
    enforcement="active",
    conditions=models.Conditions(
        ref_name=models.RefNameCondition(include=["~DEFAULT_BRANCH"], exclude=[]),
    ),
    rules=[
        models.DeletionRule(),
        models.NonFastForwardRule(),
        models.PullRequestRule(
            parameters=models.PullRequestParameters(
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
        models.BypassActor(
            actor_id=REPOSITORY_ADMIN_ROLE_ID,
            actor_type="RepositoryRole",
            bypass_mode="always",
        ),
    ],
)


def _canonical_json(ruleset: models.Ruleset) -> str:
    data = ruleset.model_dump(mode="json")
    data["rules"].sort(key=lambda rule: rule["type"])
    data["bypass_actors"].sort(key=lambda actor: json.dumps(actor, sort_keys=True))
    return json.dumps(data, indent=2, sort_keys=True)


def branch_protection(repo: models.Repository) -> list[Change]:
    branch = repo.default_branch
    try:
        gh.get(
            f"/repos/{repo.full_name}/branches/{branch}/protection",
            schema=pydantic.TypeAdapter(pydantic.JsonValue),
        )
    except gh.NotFound:
        pass
    else:
        raise SystemExit(
            f"{repo.full_name}: {branch} has classic branch protection;"
            " remove it (or convert it to a ruleset) by hand first"
        )

    active_rules = gh.get(
        f"/repos/{repo.full_name}/rules/branches/{branch}",
        schema=pydantic.TypeAdapter(list[models.ActiveRule]),
    )
    ruleset_ids = sorted({rule.ruleset_id for rule in active_rules})
    want = _canonical_json(DEFAULT_BRANCH_RULESET)
    body = DEFAULT_BRANCH_RULESET.model_dump_json()

    match ruleset_ids:
        case []:
            return [
                Change(
                    description=f"create ruleset {DEFAULT_BRANCH_RULESET.name!r}",
                    detail=want,
                    apply=lambda: gh.send("POST", f"/repos/{repo.full_name}/rulesets", body=body),
                )
            ]
        case [ruleset_id]:
            existing = gh.get(
                f"/repos/{repo.full_name}/rulesets/{ruleset_id}",
                schema=pydantic.TypeAdapter(models.Ruleset),
            )
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
                Change(
                    description=f"update ruleset {ruleset_id} ({existing.name!r})",
                    detail="\n".join(diff),
                    apply=lambda: gh.send(
                        "PUT", f"/repos/{repo.full_name}/rulesets/{ruleset_id}", body=body
                    ),
                )
            ]
        case _:
            raise SystemExit(
                f"{repo.full_name}: {branch} is covered by multiple rulesets {ruleset_ids};"
                " not touching it"
            )


# claude-setup

CLAUDE_APP_SLUG = "bmillwood-claude"


def claude_app_access(repo: models.Repository) -> list[Change]:
    owner = repo.full_name.split("/")[0]
    [installation] = [
        installation
        for page in gh.get_pages(
            "/user/installations", schema=pydantic.TypeAdapter(models.InstallationsPage)
        )
        for installation in page.installations
        if installation.app_slug == CLAUDE_APP_SLUG and installation.account.login == owner
    ]
    if installation.repository_selection == "all":
        return []
    installed_ids = {
        installed.id
        for page in gh.get_pages(
            f"/user/installations/{installation.id}/repositories",
            schema=pydantic.TypeAdapter(models.InstallationRepositoriesPage),
        )
        for installed in page.repositories
    }
    if repo.id in installed_ids:
        return []
    return [
        Change(
            description=f"add to {CLAUDE_APP_SLUG} app installation {installation.id}",
            apply=lambda: gh.send(
                "PUT", f"/user/installations/{installation.id}/repositories/{repo.id}"
            ),
        )
    ]


OPERATIONS: dict[str, list[Step]] = {
    "quality-of-life": [quality_of_life],
    "branch-protection": [branch_protection],
    "claude-setup": [branch_protection, claude_app_access],
}
