"""Group repos by the names of their Actions secrets, without changing anything.

Only repository secrets are included, not environment, Dependabot or
organisation ones.
"""

import collections
import sys
from collections.abc import Sequence

import pydantic

from repo_maintenance import github


class _Secret(pydantic.BaseModel):
    name: str


class _SecretList(pydantic.BaseModel):
    secrets: list[_Secret]


def _secret_names(repo_name: str) -> frozenset[str]:
    return frozenset(
        secret.name
        for page in github.get_pages(f"/repos/{repo_name}/actions/secrets?per_page=100")
        for secret in _SecretList.model_validate_json(page).secrets
    )


def survey(repo_names: Sequence[str]) -> bool:
    """Print each distinct set of secret names with its repos.

    Returns whether every repo could be surveyed.
    """
    all_surveyed = True
    repos_by_secrets: dict[frozenset[str], list[str]] = collections.defaultdict(list)
    for repo_name in repo_names:
        try:
            repos_by_secrets[_secret_names(repo_name)].append(repo_name)
        except github.RequestFailed as error:
            print(f"{repo_name}: {error}", file=sys.stderr)
            all_surveyed = False
    for secret_names, grouped_repos in sorted(
        repos_by_secrets.items(), key=lambda item: (-len(item[1]), sorted(item[0]))
    ):
        print(", ".join(sorted(secret_names)) or "(no secrets)")
        for repo_name in sorted(grouped_repos):
            print(f"    {repo_name}")
    return all_surveyed
