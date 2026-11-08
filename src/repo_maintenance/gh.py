"""Thin wrapper around `gh api`, so we reuse whatever authentication gh has."""

import json
import pathlib
import subprocess
import sys
import time

import jwt
import pydantic


class NotFound(Exception):
    pass


def app_jwt(*, client_id: str, private_key: pathlib.Path) -> str:
    """A short-lived token authenticating as a GitHub App itself.

    Pass it as `as_app` to authenticate a request as the app rather than as
    whoever gh is logged in as.
    """
    now = int(time.time())
    return jwt.encode(
        # Backdated a little to allow for clock skew; GitHub caps expiry at 10m.
        {"iat": now - 60, "exp": now + 540, "iss": client_id},
        private_key.read_text(),
        algorithm="RS256",
    )


def _run(path: str, *flags: str, as_app: str | None, input: str | None = None) -> str:
    if as_app is not None:
        # gh would send GH_TOKEN with the "token" scheme, which GitHub doesn't
        # accept for JWTs, but an explicit header overrides gh's own.
        flags = (*flags, "--header", f"Authorization: Bearer {as_app}")
    proc = subprocess.run(
        ["gh", "api", *flags, path],
        input=input,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # On HTTP errors gh still prints the response body to stdout.
        try:
            status = json.loads(proc.stdout).get("status")
        except (json.JSONDecodeError, AttributeError):
            status = None
        if status == "404":
            raise NotFound(path)
        sys.stderr.write(proc.stderr)
        proc.check_returncode()
    return proc.stdout


def get[T](path: str, *, schema: pydantic.TypeAdapter[T], as_app: str | None = None) -> T:
    return schema.validate_json(_run(path, as_app=as_app))


def send(method: str, path: str, *, body: str | None = None) -> None:
    if body is None:
        _run(path, "--method", method, as_app=None)
    else:
        _run(path, "--method", method, "--input", "-", as_app=None, input=body)
