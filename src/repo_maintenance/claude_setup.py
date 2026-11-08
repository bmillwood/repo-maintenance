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
# Not looked up from the slug: the app is private, and GET /apps/{slug} 404s
# for gh's token. (The JWT needs this to be known first, so asking as the app
# isn't an option either.)
APP_CLIENT_ID = "Iv23liT64156LSTP1TAa"


class Installation(pydantic.BaseModel):
    id: int


def step(repo: plan.Repository, *, app_private_key: pathlib.Path) -> list[plan.Change]:
    as_app = github.app_jwt(client_id=APP_CLIENT_ID, private_key=app_private_key)
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
