"""Pure fuzzy address matching (Requirements 7.1, 7.3).

A standard-library-only, AWS-free, deterministic module used by
``ExtractionService`` after it fetches the user's own properties via
``PropertyService.list()`` so matching is scoped to the authenticated user
(Requirement 7.5). The service attaches the suggestion to an
``ExtractedColumn`` but **never auto-applies** it — the user must confirm the
mapping in the layer-1 form (Requirement 7.2).

Approach (design "Fuzzy property matching (pure)"):

* Normalize both the extracted address and each candidate's ``address_text``:
  lowercase, strip punctuation, collapse whitespace, and standardize common US
  street-type abbreviations and directionals (``st`` → ``street``, ``ave`` →
  ``avenue``, ``apt``/``unit``/``#`` → ``unit``, ``n`` → ``north`` ...).
* Score with a Jaccard overlap over the normalized token *set*, with the
  numeric street-number token weighted so that two otherwise-identical streets
  with different street numbers do **not** collide ("12 Maple St" vs
  "120 Maple St" scores low).
* Return the best candidate as an :class:`AddressMatch` with a ``0..1``
  confidence, or ``None`` when the top score is below :data:`MATCH_THRESHOLD`
  or there are no candidates (so the column is left unmapped — Requirement
  7.3).

The module imports only :class:`~logstead.models.property.Property` for typing
and otherwise depends only on the Python standard library; it performs no I/O
and is fully unit-testable without AWS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from logstead.models.property import Property

__all__ = ["AddressMatch", "MATCH_THRESHOLD", "best_match"]


#: Minimum confidence (0..1) required to surface a suggestion. Below this the
#: column is left unmapped (``best_match`` returns ``None``). Chosen so a clear
#: street-level match (same street number + street name, differing only in
#: abbreviation/case/punctuation) comfortably clears it, while a shared street
#: name with a *different* street number falls below it.
MATCH_THRESHOLD: Final[float] = 0.5

#: Weight applied to the leading numeric street-number token when scoring. A
#: value > 1 makes the street number count for more than an ordinary word
#: token, so a street-number mismatch dominates the score and a match reinforces
#: it. This is what keeps "12 Maple St" and "120 Maple St" from colliding.
_STREET_NUMBER_WEIGHT: Final[float] = 3.0


@dataclass
class AddressMatch:
    """A fuzzy-match suggestion for one extracted address (Requirement 7.1).

    Attributes:
        property_id: The owning user's property the address best matches.
        property_name: That property's display name (for the review UI).
        confidence: Normalized similarity in ``[0.0, 1.0]``.
    """

    property_id: str
    property_name: str
    confidence: float


# Common US street-type abbreviations and directionals, mapped to a single
# canonical token so "St" / "St." / "Street" all normalize identically. Both
# the abbreviation and its canonical form map to the canonical form, so the
# mapping is idempotent.
_ABBREVIATIONS: Final[dict[str, str]] = {
    "st": "street",
    "street": "street",
    "ave": "avenue",
    "av": "avenue",
    "avenue": "avenue",
    "rd": "road",
    "road": "road",
    "blvd": "boulevard",
    "boulevard": "boulevard",
    "dr": "drive",
    "drive": "drive",
    "ln": "lane",
    "lane": "lane",
    "ct": "court",
    "court": "court",
    "pl": "place",
    "place": "place",
    "ter": "terrace",
    "terrace": "terrace",
    "cir": "circle",
    "circle": "circle",
    "hwy": "highway",
    "highway": "highway",
    "pkwy": "parkway",
    "parkway": "parkway",
    # Unit / apartment designators collapse to a single marker.
    "apt": "unit",
    "unit": "unit",
    "ste": "unit",
    "suite": "unit",
    "no": "unit",
    "num": "unit",
    # Directionals.
    "n": "north",
    "north": "north",
    "s": "south",
    "south": "south",
    "e": "east",
    "east": "east",
    "w": "west",
    "west": "west",
    "ne": "northeast",
    "northeast": "northeast",
    "nw": "northwest",
    "northwest": "northwest",
    "se": "southeast",
    "southeast": "southeast",
    "sw": "southwest",
    "southwest": "southwest",
}

# A run of digits optionally followed by a letter (e.g. "12", "120", "12a").
_STREET_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"^\d+[a-z]?$")


def _normalize_tokens(address: str) -> list[str]:
    """Normalize a free-text address into a list of canonical tokens.

    Lowercases, replaces any run of non-alphanumeric characters (punctuation,
    the ``#`` unit marker, whitespace) with a single space, splits on
    whitespace, then standardizes abbreviations/directionals. ``#12`` becomes
    the two tokens ``unit 12`` because ``#`` is stripped as punctuation and the
    bare ``12`` that follows is a number; a literal ``# 12`` normalizes the
    same way, so both spellings agree.
    """
    lowered = address.lower()
    # Treat the apartment "#" sign as the word "unit" before stripping it so a
    # "#12" style suffix is comparable to "apt 12" / "unit 12".
    lowered = lowered.replace("#", " unit ")
    # Collapse every non-alphanumeric run (punctuation + whitespace) to a space.
    cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
    raw_tokens = cleaned.split()
    return [_ABBREVIATIONS.get(tok, tok) for tok in raw_tokens]


def _is_street_number(token: str) -> bool:
    """True when a token looks like a leading street number (``12``, ``120a``)."""
    return bool(_STREET_NUMBER_RE.match(token))


def _weight(token: str) -> float:
    """Scoring weight for a single token (street numbers weigh more)."""
    return _STREET_NUMBER_WEIGHT if _is_street_number(token) else 1.0


def _weighted_jaccard(a_tokens: list[str], b_tokens: list[str]) -> float:
    """Weighted Jaccard similarity over two token *sets*.

    Each distinct token contributes its :func:`_weight` to the numerator when
    it appears in both sets and to the denominator in all cases (union). A
    street-number mismatch therefore removes a heavy term from the intersection
    while still charging both numbers to the union, which drives the score down
    sharply for "12 Maple St" vs "120 Maple St" even though "maple" + "street"
    agree.
    """
    a_set = set(a_tokens)
    b_set = set(b_tokens)
    if not a_set and not b_set:
        return 0.0

    intersection = a_set & b_set
    union = a_set | b_set

    inter_weight = sum(_weight(tok) for tok in intersection)
    union_weight = sum(_weight(tok) for tok in union)
    if union_weight == 0.0:
        return 0.0
    return inter_weight / union_weight


def best_match(address: str, candidates: list[Property]) -> AddressMatch | None:
    """Return the best fuzzy match for ``address`` among ``candidates``.

    Args:
        address: The extracted, free-text physical address of a property column.
        candidates: The authenticated user's own properties (already scoped by
            the caller via ``PropertyService.list()`` — Requirement 7.5). Each
            candidate's :attr:`Property.address_text` is normalized the same way
            as ``address`` before scoring.

    Returns:
        An :class:`AddressMatch` for the single highest-scoring candidate when
        its confidence meets :data:`MATCH_THRESHOLD`; otherwise ``None`` (no
        candidates, a blank extracted address, or every candidate below
        threshold), so the column is left unmapped (Requirement 7.3). The
        result is deterministic: ties are broken by candidate order, so the
        first-listed of equally-scoring candidates wins.
    """
    if not candidates:
        return None

    address_tokens = _normalize_tokens(address)
    if not address_tokens:
        return None

    best: AddressMatch | None = None
    for candidate in candidates:
        candidate_tokens = _normalize_tokens(candidate.address_text or "")
        if not candidate_tokens:
            continue
        score = _weighted_jaccard(address_tokens, candidate_tokens)
        if best is None or score > best.confidence:
            best = AddressMatch(
                property_id=candidate.id,
                property_name=candidate.name,
                confidence=score,
            )

    if best is None or best.confidence < MATCH_THRESHOLD:
        return None
    return best
