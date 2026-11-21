"""Helper properties for the year-end checklist.

Property 21: recent-year selection (Requirements 15.2, 15.6).
Property 22: links embed only validated ids and the year
(Requirements 10.4, 13.8, 14.6, 16.5).
"""
from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.router.handler import _ID_RE
from logstead.services.checklist import carryforward_link, property_link, recent_years

_ID_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-"
)
_property_ids = st.text(alphabet=_ID_ALPHABET, min_size=1, max_size=128)
_years = st.integers(min_value=1900, max_value=9999)
_YEAR_SEGMENTS = ("transactions", "repairs", "reports")
_PLAIN_SEGMENTS = ("assets", "loans")


# Feature: year-end-checklist, Property 22: Links embed only validated ids and the year
@settings(max_examples=100, deadline=None)
@given(
    property_id=_property_ids,
    year=_years,
    segment=st.sampled_from(_YEAR_SEGMENTS + _PLAIN_SEGMENTS),
)
def test_links_embed_only_validated_id_and_year(
    property_id: str, year: int, segment: str
) -> None:
    """**Validates: Requirements 10.4, 13.8, 14.6, 16.5**"""
    assert _ID_RE.match(property_id)
    link = property_link(property_id, segment, year)

    prefix = f"/properties/{property_id}/{segment}"
    expected = f"{prefix}?year={year}" if segment in _YEAR_SEGMENTS else prefix
    assert link == expected

    # Exactly one of the allowed shapes, with nothing else taken from the input.
    stripped = link.removeprefix(f"/properties/{property_id}/")
    assert re.fullmatch(
        r"(transactions|repairs|reports)\?year=\d{4}|assets|loans", stripped
    )
    assert link.count("?") <= 1
    assert "#" not in link and " " not in link

    # Without a year, no query string is ever added.
    assert property_link(property_id, segment) == prefix


@settings(max_examples=100, deadline=None)
@given(property_id=_property_ids, year=_years)
def test_carryforward_link_is_literal(property_id: str, year: int) -> None:
    """**Validates: Requirements 10.4, 13.8, 14.6, 16.5**"""
    assert carryforward_link() == "/carryforward"


# Feature: year-end-checklist, Property 21: Recent-year selection
@settings(max_examples=100, deadline=None)
@given(
    data_years=st.lists(st.integers(min_value=1900, max_value=2100), max_size=30),
    count=st.integers(min_value=1, max_value=40),
)
def test_recent_years_selects_newest_distinct(
    data_years: list[int], count: int
) -> None:
    """**Validates: Requirements 15.2, 15.6**"""
    distinct = set(data_years)
    result = recent_years(data_years, count)

    assert len(result) == min(count, len(distinct))
    assert len(set(result)) == len(result)
    assert result == sorted(result, reverse=True)
    assert set(result) <= distinct
    omitted = distinct - set(result)
    if result and omitted:
        assert min(result) >= max(omitted)


def test_recent_years_empty_input() -> None:
    """**Validates: Requirements 15.2, 15.6**"""
    assert recent_years([], 3) == []
    assert recent_years(set(), 1) == []


def test_recent_years_with_gaps_and_duplicates() -> None:
    """**Validates: Requirements 15.2, 15.6**"""
    assert recent_years([2019, 2024, 2021, 2024, 2015], 3) == [2024, 2021, 2019]
