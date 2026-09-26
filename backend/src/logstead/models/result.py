"""A ``Result[T]`` success/typed-error wrapper.

Services return ``Result`` values so the router can map a success to a
2xx response and a typed error to the appropriate HTTP status code
(validation error -> 400 with the offending field, not found -> 404).

The design (Components and Interfaces) refers to ``Result[T]`` as a
"success/typed-error outcome". This module provides that as a small
tagged union of :class:`Ok` and :class:`Error`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

T = TypeVar("T")

# The kinds of typed errors the service layer can surface. These map to
# HTTP status codes in the router (validation -> 400, not_found -> 404,
# conflict -> 409, unavailable -> 503).
ErrorKind = Literal[
    "validation",
    "not_found",
    "conflict",
    "unavailable",
    "unauthorized",
]


@dataclass(frozen=True)
class Error:
    """A typed error outcome.

    Attributes:
        kind: The category of error, used to select an HTTP status code.
        message: A human-readable message safe to surface to the client.
        field: The offending field name, when the error is field-specific
            (e.g., validation messages that "identify the missing field").
    """

    kind: ErrorKind
    message: str
    field: str | None = None


@dataclass(frozen=True)
class Ok(Generic[T]):
    """A success outcome carrying a value."""

    value: T


@dataclass(frozen=True)
class Result(Generic[T]):
    """A success/typed-error outcome.

    Exactly one of ``ok`` or ``error`` is set. Use the :meth:`success` and
    :meth:`failure` constructors rather than instantiating directly, and
    check :attr:`is_ok` before reading :attr:`value`.
    """

    ok: Ok[T] | None = None
    error: Error | None = None

    @staticmethod
    def success(value: T) -> "Result[T]":
        return Result(ok=Ok(value))

    @staticmethod
    def failure(
        kind: ErrorKind, message: str, field: str | None = None
    ) -> "Result[T]":
        return Result(error=Error(kind=kind, message=message, field=field))

    @property
    def is_ok(self) -> bool:
        return self.error is None

    @property
    def value(self) -> T:
        """Return the success value.

        Raises:
            ValueError: If this result represents an error.
        """
        if self.ok is None:
            raise ValueError("Result has no value; it represents an error")
        return self.ok.value
