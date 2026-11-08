"""Vocabulary shared by all operations.

An operation is a list of steps. Each step inspects a repo and returns the
changes needed to bring it in line, so that an empty list means it's in sync.
"""

import dataclasses
from collections.abc import Callable
from typing import Literal

import pydantic


class CannotPlan(Exception):
    """The repo is in a state we don't know how to bring in line."""


class Repository(pydantic.BaseModel):
    id: int
    full_name: str
    default_branch: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class ApiCall:
    method: Literal["POST", "PUT", "PATCH", "DELETE"]
    path: str
    body: pydantic.JsonValue = None

    def __str__(self) -> str:
        return f"{self.method} {self.path}"


@dataclasses.dataclass(frozen=True, kw_only=True)
class ManualStep:
    """Something we can't (or would rather not) do via the API."""

    instruction: str

    def __str__(self) -> str:
        return self.instruction


@dataclasses.dataclass(frozen=True, kw_only=True)
class Change:
    description: str
    detail: str = ""
    action: ApiCall | ManualStep


type Step = Callable[[Repository], list[Change]]
