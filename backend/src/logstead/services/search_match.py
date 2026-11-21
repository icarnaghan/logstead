"""Pure matching, ranking and link helpers for global search. No I/O.

The query is plain text: it is never compiled into a pattern, so ``*``, ``%``,
``\\`` and ``.`` match literally. Only the text fields the caller passes in are
searched (never amounts, dates or category labels).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from datetime import date
from typing import Any, Final

RANK_EXACT: Final[int] = 0
RANK_WORD_PREFIX: Final[int] = 1
RANK_SUBSTRING: Final[int] = 2

_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_YEAR_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}$")
_WORD_SPLIT: Final[re.Pattern[str]] = re.compile(r"\s+")


def normalize(text: str) -> str:
    """NFKC, case-fold, collapse whitespace. Idempotent."""
    out = unicodedata.normalize("NFKC", text).casefold()
    # casefold can produce characters that change under NFKC; settle first.
    out = unicodedata.normalize("NFKC", out).casefold()
    return " ".join(out.split())


def tokenize(query: str, max_tokens: int) -> list[str]:
    """Split a query into at most ``max_tokens`` normalized tokens."""
    norm = normalize(query)
    if not norm or max_tokens <= 0:
        return []
    return norm.split(" ")[:max_tokens]


def _has_word_prefix(words: Sequence[str], token: str) -> bool:
    return any(w.startswith(token) for w in words)


def match_rank(
    tokens: Sequence[str], fields: Sequence[tuple[str, str]]
) -> tuple[int, str] | None:
    """Rank a record against the tokens.

    ``fields`` is ``[(name, raw_text)]``. Every token must occur in the joined
    normalized text. Returns ``(rank, matched_field)`` or ``None``:
    0 a whole field equals the query, 1 every token starts a word, 2 substring.
    """
    if not tokens:
        return None
    normed = [(name, normalize(text)) for name, text in fields]
    joined = " ".join(t for _, t in normed)
    if not all(tok in joined for tok in tokens):
        return None

    query = " ".join(tokens)
    for name, text in normed:
        if text == query:
            return RANK_EXACT, name

    words = _WORD_SPLIT.split(joined)
    rank = (
        RANK_WORD_PREFIX
        if all(_has_word_prefix(words, tok) for tok in tokens)
        else RANK_SUBSTRING
    )
    for name, text in normed:
        if tokens[0] in text:
            return rank, name
    # Every token matched but the first spans no single field (cannot happen
    # for whitespace-free tokens; kept as a deterministic fallback).
    return rank, normed[0][0]


def _date_ordinal(value: Any) -> int:
    if isinstance(value, date):
        return value.toordinal()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10]).toordinal()
        except ValueError:
            return 0
    return 0


def sort_key(hit: Any, rank: int | None = None) -> tuple[int, int, str, str, str]:
    """Order: rank, most recent date first, title, id.

    ``hit`` needs ``date``, ``title`` and ``id`` attributes (or mapping keys);
    ``rank`` defaults to ``hit.rank`` when present.
    """

    def get(name: str, default: Any = None) -> Any:
        if isinstance(hit, dict):
            return hit.get(name, default)
        return getattr(hit, name, default)

    r = rank if rank is not None else get("rank", RANK_SUBSTRING)
    title = get("title") or ""
    return (
        int(r),
        -_date_ordinal(get("date")),
        normalize(title),
        title,
        str(get("id") or ""),
    )


def _valid_id(value: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise ValueError("invalid id for link")
    return value


def link_for(
    kind: str,
    property_id: str | None,
    record_id: str | None,
    year: int | str | None = None,
) -> str:
    """Build an in-app link from validated ids. Raises ValueError otherwise."""
    if kind == "business":
        return f"/businesses/{_valid_id(record_id or '')}"
    pid = _valid_id(property_id or "")
    if kind == "property":
        return f"/properties/{pid}"
    rid = _valid_id(record_id or "")
    if kind in ("transaction", "itemized_entry"):
        y = str(year)
        if not _YEAR_RE.match(y):
            raise ValueError("invalid year for link")
        page = "transactions" if kind == "transaction" else "repairs"
        return f"/properties/{pid}/{page}?year={y}&focus={rid}"
    if kind == "asset":
        return f"/properties/{pid}/assets?focus={rid}"
    if kind == "loan":
        return f"/properties/{pid}/loans?focus={rid}"
    raise ValueError(f"unknown kind: {kind}")
