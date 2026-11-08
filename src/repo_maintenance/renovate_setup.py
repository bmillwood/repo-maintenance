"""Give a repo the credentials for running Renovate as a GitHub App.

GitHub has no user-level Actions secrets, so every repo that runs Renovate
via bmillwood/renovateconfig's workflow needs its own RENOVATE_APP_CLIENT_ID
and RENOVATE_APP_PRIVATE_KEY.

Secrets that already exist are left alone. They're write-only, so there's no
telling a current one from a stale one, and overwriting regardless would make
every run a rotation you didn't ask for. Delete one by hand to refresh it.
"""

import base64
import pathlib

import nacl.public
import pydantic

from repo_maintenance import github, plan


class PublicKey(pydantic.BaseModel):
    """GET /repos/{repo}/actions/secrets/public-key"""

    key_id: str
    key: str


def _private_key(app_dir: pathlib.Path) -> pathlib.Path:
    # Fails rather than picking one, so that a rotation that leaves the
    # superseded key lying around can't quietly win.
    keys = list(app_dir.glob("*.private-key.pem"))
    if len(keys) != 1:
        raise plan.CannotPlan(
            f"want exactly one *.private-key.pem in {app_dir}, found {len(keys)}"
        )
    [key] = keys
    return key


def step(repo: plan.Repository, *, app_dir: pathlib.Path) -> list[plan.Change]:
    # Values are only read for secrets that are missing, so that an
    # already-configured repo doesn't need the key to hand.
    wanted = {
        "RENOVATE_APP_CLIENT_ID": lambda: app_dir / "client_id.txt",
        "RENOVATE_APP_PRIVATE_KEY": lambda: _private_key(app_dir),
    }
    missing = {}
    for name, source in wanted.items():
        try:
            github.request("GET", f"/repos/{repo.full_name}/actions/secrets/{name}")
        except github.NotFound:
            missing[name] = source()
    if not missing:
        return []

    public_key = PublicKey.model_validate_json(
        github.request("GET", f"/repos/{repo.full_name}/actions/secrets/public-key")
    )
    sealed_box = nacl.public.SealedBox(
        nacl.public.PublicKey(base64.b64decode(public_key.key))
    )
    return [
        plan.Change(
            description=f"set Actions secret {name} from {path}",
            action=plan.ApiCall(
                method="PUT",
                path=f"/repos/{repo.full_name}/actions/secrets/{name}",
                body={
                    "key_id": public_key.key_id,
                    "encrypted_value": base64.b64encode(
                        # Without the trailing newline, like `gh secret set`.
                        sealed_box.encrypt(path.read_bytes().removesuffix(b"\n"))
                    ).decode(),
                },
            ),
        )
        for name, path in missing.items()
    ]
