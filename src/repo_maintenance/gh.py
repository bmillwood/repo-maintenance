"""Thin wrapper around `gh api`, so we reuse whatever authentication gh has."""

import json
import subprocess
import sys

import pydantic


class NotFound(Exception):
    pass


def _run(path: str, *flags: str, input: str | None = None) -> str:
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


def get[T](path: str, *, schema: pydantic.TypeAdapter[T]) -> T:
    return schema.validate_json(_run(path))


def get_pages[T](path: str, *, schema: pydantic.TypeAdapter[T]) -> list[T]:
    pages = json.loads(_run(path, "--paginate", "--slurp"))
    return [schema.validate_python(page) for page in pages]


def send(method: str, path: str, *, body: str | None = None) -> None:
    if body is None:
        _run(path, "--method", method)
    else:
        _run(path, "--method", method, "--input", "-", input=body)
