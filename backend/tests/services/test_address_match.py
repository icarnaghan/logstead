"""Unit tests for the pure fuzzy address matcher (task 4.2).

Covers Requirement 7.3 (and the matcher half of 7.1): an exact normalized
match returns high confidence; "12 Maple St" vs "120 Maple St" do **not**
collide because their street numbers differ; a below-threshold address and an
empty candidate list both return ``None`` (the column is left unmapped); and
the best of several candidates is chosen deterministically.

The matcher is pure and AWS-free, so these tests construct ``Property`` values
directly and call :func:`best_match` with no DynamoDB/S3/boto3 involvement.
"""

from __future__ import annotations

from logstead.models.property import Property
from logstead.services.address_match import (
    MATCH_THRESHOLD,
    AddressMatch,
    best_match,
)


def _prop(prop_id: str, name: str, address_text: str) -> Property:
    """Build a minimal ``Property`` carrying just id / name / address."""
    return Property(
        id=prop_id,
        user_id="user-1",
        name=name,
        address_text=address_text,
    )


# --- Exact / near-exact normalized match ------------------------------------

def test_exact_normalized_match_returns_high_confidence():
    """Case/punctuation/abbreviation differences only → high confidence match."""
    candidates = [_prop("p1", "Maple Duplex", "12 Maple Street")]

    match = best_match("12 MAPLE ST.", candidates)

    assert match is not None
    assert isinstance(match, AddressMatch)
    assert match.property_id == "p1"
    assert match.property_name == "Maple Duplex"
    # Normalizes to identical token sets → perfect similarity.
    assert match.confidence == 1.0


def test_abbreviation_and_directional_normalization_matches():
    """Directionals and street-type abbreviations normalize to the same tokens."""
    candidates = [_prop("p1", "Oak House", "100 North Oak Avenue")]

    match = best_match("100 N Oak Ave", candidates)

    assert match is not None
    assert match.property_id == "p1"
    assert match.confidence == 1.0


def test_unit_designators_normalize():
    """``#4`` and ``Apt 4`` normalize to the same unit tokens."""
    candidates = [_prop("p1", "Elm Units", "5 Elm St Apt 4")]

    match = best_match("5 Elm Street #4", candidates)

    assert match is not None
    assert match.property_id == "p1"
    assert match.confidence >= MATCH_THRESHOLD


# --- Street-number discrimination (the key anti-collision property) ---------

def test_different_street_number_does_not_match():
    """"12 Maple St" vs "120 Maple St" must NOT collide (different number)."""
    candidates = [_prop("p1", "120 Maple", "120 Maple Street")]

    match = best_match("12 Maple St", candidates)

    assert match is None


def test_same_street_number_wins_over_same_street_name():
    """Among same-street candidates, the matching street number is chosen."""
    candidates = [
        _prop("wrong", "120 Maple", "120 Maple Street"),
        _prop("right", "12 Maple", "12 Maple Street"),
    ]

    match = best_match("12 Maple St", candidates)

    assert match is not None
    assert match.property_id == "right"


# --- Below-threshold / empty → None (unmapped) ------------------------------

def test_below_threshold_returns_none():
    """A wholly unrelated address stays unmapped."""
    candidates = [_prop("p1", "Maple Duplex", "12 Maple Street")]

    match = best_match("987 Sunset Boulevard", candidates)

    assert match is None


def test_empty_candidates_returns_none():
    """No candidates → None."""
    assert best_match("12 Maple St", []) is None


def test_blank_address_returns_none():
    """A blank/whitespace extracted address cannot match anything."""
    candidates = [_prop("p1", "Maple Duplex", "12 Maple Street")]

    assert best_match("   ", candidates) is None


# --- Best-of-several selection ----------------------------------------------

def test_best_of_several_candidates_is_chosen():
    """The highest-scoring candidate among several is returned."""
    candidates = [
        _prop("far", "Sunset", "987 Sunset Boulevard"),
        _prop("partial", "Maple Ave", "12 Maple Avenue"),
        _prop("exact", "Maple St", "12 Maple Street"),
    ]

    match = best_match("12 Maple St", candidates)

    assert match is not None
    assert match.property_id == "exact"
    assert match.confidence == 1.0


def test_confidence_is_within_unit_interval():
    """Confidence is always a normalized 0..1 value when a match is returned."""
    candidates = [_prop("p1", "Maple Duplex", "12 Maple St Apt 2")]

    match = best_match("12 Maple Street", candidates)

    assert match is not None
    assert 0.0 <= match.confidence <= 1.0
