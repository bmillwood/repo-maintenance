"""Minimal GitHub REST API client.

Requests are made in-process rather than via `gh api`, so that tokens never
appear on a command line. By default they authenticate with gh's token.
"""

import functools
import pathlib
import re
import subprocess
import time
import urllib.error
import urllib.parse
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


def current_repo() -> str:
    """OWNER/REPO for the repo gh considers current.

    If there isn't one, gh explains why on stderr.
    """
    return subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()


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
    content, _ = _request(
        method, f"https://api.github.com{path}", body=body, token=token
    )
    return content


def get_pages(path: str, *, token: pydantic.SecretStr | None = None) -> list[bytes]:
    """GET every page of a paginated list, following the Link headers."""
    pages = []
    url: str | None = f"https://api.github.com{path}"
    while url is not None:
        content, url = _request("GET", url, body=None, token=token)
        pages.append(content)
    return pages


def _request(
    method: str, url: str, *, body: str | None, token: pydantic.SecretStr | None
) -> tuple[bytes, str | None]:
    """The response body, and the URL of the next page if there is one."""
    if token is None:
        token = gh_token()
    req = urllib.request.Request(
        url=url,
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
            next_page = re.search(
                r'<([^>]+)>; rel="next"', response.headers["Link"] or ""
            )
            return response.read(), next_page and next_page[1]
    except urllib.error.HTTPError as error:
        text = error.read().decode(errors="replace")
        try:
            message = ErrorBody.model_validate_json(text).message
        except pydantic.ValidationError:
            message = text
        exception = NotFound if error.code == 404 else RequestFailed
        split = urllib.parse.urlsplit(url)
        path = split.path + (f"?{split.query}" if split.query else "")
        raise exception(
            method=method, path=path, status=error.code, message=message
        ) from None
