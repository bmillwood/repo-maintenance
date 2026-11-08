"""Set repository options that should always be on.

Currently just deleting head branches when PRs are merged.
"""

import pydantic

from repo_maintenance import github, plan


class Settings(pydantic.BaseModel):
    """The repository settings we manage, as in GET/PATCH /repos/{repo}."""

    delete_branch_on_merge: bool


DESIRED = Settings(delete_branch_on_merge=True)


def step(repo: plan.Repository) -> list[plan.Change]:
    have = Settings.model_validate_json(
        github.request("GET", f"/repos/{repo.full_name}")
    )
    have_fields = have.model_dump()
    patch = {k: v for k, v in DESIRED.model_dump().items() if have_fields[k] != v}
    if not patch:
        return []
    return [
        plan.Change(
            description="update repository settings",
            detail="\n".join(
                f"{k}: {have_fields[k]!r} -> {v!r}" for k, v in patch.items()
            ),
            action=plan.ApiCall(
                method="PATCH", path=f"/repos/{repo.full_name}", body=patch
            ),
        )
    ]
