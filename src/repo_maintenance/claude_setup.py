"""Run branch-protection, and give the bmillwood-claude GitHub App access.

Checks whether the repo is in the app's installation by authenticating as the
app itself, since gh's token can't list an installation's repositories. The
API for adding a repo to an installation doesn't accept gh's token either, so
that part is left to you in the browser.
"""

import pathlib

import pydantic

from repo_maintenance import github, plan

APP_SLUG = "bmillwood-claude"


class App(pydantic.BaseModel):
    client_id: str


class Installation(pydantic.BaseModel):
    id: int


def step(repo: plan.Repository, *, app_private_key: pathlib.Path) -> list[plan.Change]:
    app = App.model_validate_json(github.request("GET", f"/apps/{APP_SLUG}"))
    as_app = github.app_jwt(client_id=app.client_id, private_key=app_private_key)
    try:
        # 404s if the repo isn't in the installation.
        github.request("GET", f"/repos/{repo.full_name}/installation", token=as_app)
    except github.NotFound:
        pass
    else:
        return []
    owner = repo.full_name.split("/")[0]
    installation = Installation.model_validate_json(
        github.request("GET", f"/users/{owner}/installation", token=as_app)
    )
    settings_url = f"https://github.com/settings/installations/{installation.id}"
    return [
        plan.Change(
            description=f"add to {APP_SLUG} app installation (by hand)",
            action=plan.ManualStep(
                instruction=f"Add {repo.full_name} at {settings_url}"
            ),
        )
    ]
