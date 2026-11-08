"""Shapes of the GitHub API payloads we read and write.

Models we use to *read* things default to ignoring fields we don't mention,
since GitHub responses have lots of fields we don't care about. Models that
describe configuration we *compare* against our desired state instead forbid
extra fields, so that a setting we don't know about can't make us think a
repo is in sync when it isn't.
"""

from typing import Annotated, Literal

import pydantic


class Strict(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)


# Repositories


class RepositorySettings(pydantic.BaseModel):
    """The subset of repository settings managed by quality-of-life."""

    delete_branch_on_merge: bool


class Repository(RepositorySettings):
    id: int
    full_name: str
    default_branch: str


# Rulesets


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
    """An entry in the list of rules that apply to a branch."""

    type: str
    ruleset_id: int


# App installations


class Account(pydantic.BaseModel):
    login: str


class Installation(pydantic.BaseModel):
    id: int
    app_slug: str
    account: Account
    repository_selection: Literal["all", "selected"]


class InstallationsPage(pydantic.BaseModel):
    installations: list[Installation]


class RepositoryRef(pydantic.BaseModel):
    id: int
    full_name: str


class InstallationRepositoriesPage(pydantic.BaseModel):
    repositories: list[RepositoryRef]
