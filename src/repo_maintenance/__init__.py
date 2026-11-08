"""Idempotently apply packages of GitHub configuration.

Operates on the named repos, and those of any --owner, or the current repo if
neither is given.
Authenticates with gh's token (via `gh auth token`), which needs to belong to
a repo admin.

By default, only reports what would change, exiting 1 if anything would.
With --apply, makes the changes, then checks again that nothing is left.
"""

import io
import json
import pathlib
import subprocess
import sys
from collections.abc import Sequence
from typing import Annotated

import cyclopts
import pydantic

from repo_maintenance import (
    branch_protection,
    claude_setup,
    github,
    plan,
    quality_of_life,
    renovate_setup,
)

app = cyclopts.App(help=__doc__)

Repo = Annotated[str, cyclopts.Parameter(name="OWNER/REPO")]
Owner = Annotated[
    tuple[str, ...],
    cyclopts.Parameter(
        negative=(),
        metavar="OWNER",
        show_default=False,
        help="Also operate on all of this user or organisation's repos that you"
        " administer, except forks and archived ones. Can be repeated.",
    ),
]
Apply = Annotated[
    bool,
    cyclopts.Parameter(
        negative=(), help="Make the changes, then check again that nothing is left."
    ),
]


def _print_changes(*, repo_name: str, changes: list[plan.Change]) -> None:
    if not changes:
        print(f"{repo_name}: in sync")
    for change in changes:
        print(f"{repo_name}: {change.description}")
        for line in change.detail.splitlines():
            print(f"    {line}")


def _plan(*, repo_name: str, steps: Sequence[plan.Step]) -> list[plan.Change] | None:
    """The changes needed, or None (having said why) if we couldn't tell."""
    try:
        repo = plan.Repository.model_validate_json(
            github.request("GET", f"/repos/{repo_name}")
        )
        changes = [change for step in steps for change in step(repo)]
    except (github.RequestFailed, plan.CannotPlan) as error:
        print(f"{repo_name}: {error}", file=sys.stderr)
        return None
    _print_changes(repo_name=repo_name, changes=changes)
    return changes


def _do(action: plan.ApiCall | plan.ManualStep) -> None:
    match action:
        case plan.ApiCall(method=method, path=path, body=body):
            github.request(
                method, path, body=None if body is None else json.dumps(body)
            )
        case plan.ManualStep(instruction=instruction):
            input(f"{instruction}, then press Enter: ")


def _sync(*, repo_name: str, steps: Sequence[plan.Step], apply: bool) -> bool:
    """Whether the repo is (now) in sync."""
    changes = _plan(repo_name=repo_name, steps=steps)
    if not changes or not apply:
        return changes == []
    for change in changes:
        print(f"{repo_name}: {change.action}")
        try:
            _do(change.action)
        except github.RequestFailed as error:
            print(f"{repo_name}: {error}", file=sys.stderr)
            print(f"{repo_name}: not attempting any further changes", file=sys.stderr)
            break
    print(f"{repo_name}: re-checking")
    return _plan(repo_name=repo_name, steps=steps) == []


class _Owner(pydantic.BaseModel):
    login: str


class _Permissions(pydantic.BaseModel):
    admin: bool


class _ListedRepo(pydantic.BaseModel):
    full_name: str
    owner: _Owner
    fork: bool
    archived: bool
    permissions: _Permissions


def _owner_repos(owner: str) -> list[str]:
    # Unlike /users/{owner}/repos, this includes private repos, and covers
    # organisations as well as users.
    listed = [
        repo
        for page in github.get_pages(
            "/user/repos?affiliation=owner,organization_member&per_page=100"
        )
        for repo in pydantic.TypeAdapter(list[_ListedRepo]).validate_json(page)
    ]
    return [
        repo.full_name
        for repo in listed
        if repo.owner.login.lower() == owner.lower()
        and repo.permissions.admin
        and not repo.fork
        and not repo.archived
    ]


def _run(
    *,
    repos: Sequence[str],
    owners: Sequence[str],
    steps: Sequence[plan.Step],
    apply: bool,
) -> None:
    repos = list(repos)
    for owner in owners:
        try:
            repos += _owner_repos(owner)
        except github.RequestFailed as error:
            print(f"listing repos: {error}", file=sys.stderr)
            sys.exit(1)
    if not repos and not owners:
        try:
            repos = [github.current_repo()]
        except subprocess.CalledProcessError as error:
            print("No OWNER/REPO given, and no current repo.", file=sys.stderr)
            sys.exit(error.returncode)
    results = [
        _sync(repo_name=repo_name, steps=steps, apply=apply) for repo_name in repos
    ]
    sys.exit(0 if all(results) else 1)


@app.command(name="quality-of-life", help=quality_of_life.__doc__)
def _quality_of_life(*repos: Repo, owner: Owner = (), apply: Apply = False) -> None:
    _run(repos=repos, owners=owner, steps=[quality_of_life.step], apply=apply)


@app.command(name="branch-protection", help=branch_protection.__doc__)
def _branch_protection(*repos: Repo, owner: Owner = (), apply: Apply = False) -> None:
    _run(repos=repos, owners=owner, steps=[branch_protection.step], apply=apply)


@app.command(name="claude-setup", help=claude_setup.__doc__)
def _claude_setup(
    *repos: Repo,
    app_private_key: Annotated[
        cyclopts.types.ExistingFile,
        cyclopts.Parameter(help=f"Private key of the {claude_setup.APP_SLUG} app."),
    ],
    owner: Owner = (),
    apply: Apply = False,
) -> None:
    _run(
        repos=repos,
        owners=owner,
        steps=[
            branch_protection.step,
            lambda repo: claude_setup.step(repo, app_private_key=app_private_key),
        ],
        apply=apply,
    )


@app.command(name="renovate-setup", help=renovate_setup.__doc__)
def _renovate_setup(
    *repos: Repo,
    # The noqa on the default below is for B008, which flags function calls in
    # defaults: they're evaluated once, when the function is defined, so a
    # mutable result would be shared between calls. Paths are immutable, so
    # that's harmless, and evaluating it up front lets --help show it.
    app_dir: Annotated[
        # Not ExistingDirectory: it's only needed if there's something to set.
        pathlib.Path,
        cyclopts.Parameter(
            env_var="RENOVATE_APP_DIR",
            help="Directory with the Renovate app's client_id.txt and private key.",
        ),
    ] = pathlib.Path.home() / ".config/renovate-app",  # noqa: B008
    owner: Owner = (),
    apply: Apply = False,
) -> None:
    _run(
        repos=repos,
        owners=owner,
        steps=[lambda repo: renovate_setup.step(repo, app_dir=app_dir)],
        apply=apply,
    )


def main() -> None:
    # So that stdout and stderr interleave sensibly even when piped.
    assert isinstance(sys.stdout, io.TextIOWrapper)
    sys.stdout.reconfigure(line_buffering=True)
    app()
