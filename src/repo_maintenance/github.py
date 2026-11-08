"""Minimal GitHub REST API client.

Requests are made in-process rather than via `gh api`, so that tokens never
appear on a command line. By default they authenticate with gh's token.
"""

import functools
import pathlib
import subprocess
import time
import urllib.error
import urllib.request

import jwt
import pydantic


class RequestFailed(Exception):
    def __init__(self, *, method: str, path: str, status: int, message: str) -> None:
        super().__init__(f"{method} {path}: HTTP {status}: {message}")
        self.status = status


class NotFound(RequestFailed):
    pass


class ErrorBody(pydantic.BaseModel):
    message: str


@functools.cache
def gh_token() -> pydantic.SecretStr:
    return pydantic.SecretStr(
        subprocess.run(
            ["gh", "auth", "token"], check=True, capture_output=True, text=True
        ).stdout.strip()
    )


def app_jwt(*, client_id: str, private_key: pathlib.Path) -> pydantic.SecretStr:
    """A short-lived token authenticating as a GitHub App itself."""
    now = int(time.time())
    return pydantic.SecretStr(
        jwt.encode(
            # Backdated a little to allow for clock skew; GitHub caps expiry at 10m.
            {"iat": now - 60, "exp": now + 540, "iss": client_id},
            private_key.read_text(),
            algorithm="RS256",
        )
    )


def request(
    method: str,
    path: str,
    *,
    body: str | None = None,
    token: pydantic.SecretStr | None = None,
) -> bytes:
    """Make a request, authenticated with `token` if given, or gh's otherwise."""
    if token is None:
        token = gh_token()
    req = urllib.request.Request(
        url=f"https://api.github.com{path}",
        method=method,
        data=None if body is None else body.encode(),
        headers={
            "Authorization": f"Bearer {token.get_secret_value()}",
            "Accept": "application/vnd.github+json",
            # Otherwise urllib labels any body as form-encoded.
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        text = error.read().decode(errors="replace")
        try:
            message = ErrorBody.model_validate_json(text).message
        except pydantic.ValidationError:
            message = text
        exception = NotFound if error.code == 404 else RequestFailed
        raise exception(
            method=method, path=path, status=error.code, message=message
        ) from None
