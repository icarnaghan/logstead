"""Helpers for logging exceptions without leaking values.

Exception messages (and therefore standard tracebacks) can embed request
payloads, amounts, addresses or presigned URLs, for example a pydantic or
``ValueError`` message that echoes the offending input. ``exc_summary`` keeps
the diagnostic shape (exception types along the cause chain and the code
location of each frame) and drops every message and local value.
"""

from __future__ import annotations

import traceback

__all__ = ["exc_summary"]

_MAX_CHAIN = 5
_MAX_FRAMES = 12


def exc_summary(exc: BaseException) -> str:
    """Return ``Type <- CauseType @ file:line in func; ...`` with no messages."""
    types: list[str] = []
    cur: BaseException | None = exc
    while cur is not None and len(types) < _MAX_CHAIN:
        types.append(type(cur).__name__)
        cur = cur.__cause__ or cur.__context__
    frames = traceback.extract_tb(exc.__traceback__)[-_MAX_FRAMES:]
    where = " > ".join(
        f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno} {f.name}" for f in frames
    )
    return f"{' <- '.join(types)} @ {where}" if where else " <- ".join(types)
