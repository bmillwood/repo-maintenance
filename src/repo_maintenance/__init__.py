import argparse
import pathlib
import sys

import pydantic

from repo_maintenance import gh, models, operations


def plan(
    *, operation: str, repo_name: str, config: operations.Config
) -> list[operations.Change]:
    repo = gh.get(f"/repos/{repo_name}", schema=pydantic.TypeAdapter(models.Repository))
    return [
        change
        for step in operations.OPERATIONS[operation]
        for change in step(repo, config=config)
    ]


def report(*, repo_name: str, changes: list[operations.Change]) -> None:
    if not changes:
        print(f"{repo_name}: in sync")
    for change in changes:
        print(f"{repo_name}: {change.description}")
        if change.detail:
            for line in change.detail.splitlines():
                print(f"    {line}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Idempotently apply packages of GitHub configuration."
        " By default, only reports what would change, exiting 1 if anything would.",
    )
    parser.add_argument("operation", choices=operations.OPERATIONS)
    parser.add_argument("repos", nargs="+", metavar="OWNER/REPO")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="make the changes, then check again that nothing is left to change",
    )
    parser.add_argument(
        "--app-private-key",
        type=pathlib.Path,
        help=f"private key for the {operations.CLAUDE_APP_SLUG} app (needed by claude-setup)",
    )
    args = parser.parse_args()
    config = operations.Config(app_private_key=args.app_private_key)

    out_of_sync = False
    for repo_name in args.repos:
        changes = plan(operation=args.operation, repo_name=repo_name, config=config)
        report(repo_name=repo_name, changes=changes)
        if args.apply and changes:
            for change in changes:
                change.apply()
            changes = plan(operation=args.operation, repo_name=repo_name, config=config)
            if changes:
                print(f"{repo_name}: still out of sync after applying changes!")
                report(repo_name=repo_name, changes=changes)
            else:
                print(f"{repo_name}: applied, now in sync")
        out_of_sync = out_of_sync or bool(changes)
    sys.exit(1 if out_of_sync else 0)
