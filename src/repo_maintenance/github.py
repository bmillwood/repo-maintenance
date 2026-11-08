"""Minimal GitHub REST API client.

Requests are made in-process rather than via `gh api`, so that tokens never
appear on a command line. By default they authenticate with gh's token.
"""

import functools
import json
import pathlib
import subprocess
import time
import urllib.error
import urllib.request

import jwt

API = "https://api.github.com"


class RequestFailed(Exception):
    def __init__(self, *, method: str, path: str, status: int, message: str) -> None:
        super().__init__(f"{method} {path}: HTTP {status}: {message}")
        self.status = status


class NotFound(RequestFailed):
    pass


@functools.cache
def gh_token() -> str:
    return subprocess.run(
        ["gh", "auth", "token"], check=True, capture_output=True, text=True
    ).stdout.strip()


def app_jwt(*, client_id: str, private_key: pathlib.Path) -> str:
    """A short-lived token authenticating as a GitHub App itself."""
    now = int(time.time())
    return jwt.encode(
        # Backdated a little to allow for clock skew; GitHub caps expiry at 10m.
        {"iat": now - 60, "exp": now + 540, "iss": client_id},
        private_key.read_text(),
        algorithm="RS256",
    )


def request(
    method: str, path: str, *, body: str | None = None, token: str | None = None
) -> bytes:
    """Make a request, authenticated with `token` if given, or gh's otherwise."""
    req = urllib.request.Request(
        url=f"{API}{path}",
        method=method,
        data=None if body is None else body.encode(),
        headers={
            "Authorization": f"Bearer {token or gh_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        text = error.read().decode(errors="replace")
        try:
            message = json.loads(text)["message"]
        except (json.JSONDecodeError, KeyError, TypeError):
            message = text
        exception = NotFound if error.code == 404 else RequestFailed
        raise exception(method=method, path=path, status=error.code, message=message) from None
