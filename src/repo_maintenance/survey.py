"""Read-only reports grouping repos by some aspect of their configuration."""

import collections
import sys
from collections.abc import Callable, Sequence

import pydantic

from repo_maintenance import github


class _Secret(pydantic.BaseModel):
    name: str


class _SecretList(pydantic.BaseModel):
    secrets: list[_Secret]


def secret_names(repo_name: str) -> frozenset[str]:
    """Group repos by the names of their Actions secrets.

    Only repository secrets are included, not environment, Dependabot or
    organisation ones.
    """
    return frozenset(
        secret.name
        for page in github.get_pages(f"/repos/{repo_name}/actions/secrets?per_page=100")
        for secret in _SecretList.model_validate_json(page).secrets
    )


class _Collaborator(pydantic.BaseModel):
    login: str
    role_name: str


def collaborators(repo_name: str) -> frozenset[str]:
    """Group repos by their collaborators and roles, other than the repo's owner.

    Pending invitations aren't included.
    """
    owner = repo_name.split("/")[0]
    return frozenset(
        f"{collaborator.login} ({collaborator.role_name})"
        for page in github.get_pages(f"/repos/{repo_name}/collaborators?per_page=100")
        for collaborator in pydantic.TypeAdapter(list[_Collaborator]).validate_json(
            page
        )
        if collaborator.login.lower() != owner.lower()
    )


def survey(
    repo_names: Sequence[str], *, describe: Callable[[str], frozenset[str]]
) -> bool:
    """Print each distinct description with its repos, most common first.

    Returns whether every repo could be described.
    """
    all_described = True
    repos_by_description: dict[frozenset[str], list[str]] = collections.defaultdict(
        list
    )
    for repo_name in repo_names:
        try:
            repos_by_description[describe(repo_name)].append(repo_name)
        except github.RequestFailed as error:
            print(f"{repo_name}: {error}", file=sys.stderr)
            all_described = False
    for description, grouped_repos in sorted(
        repos_by_description.items(),
        key=lambda item: (-len(item[1]), sorted(item[0])),
    ):
        print(", ".join(sorted(description)) or "(none)")
        for repo_name in sorted(grouped_repos):
            print(f"    {repo_name}")
    return all_described
