"""Property-based test for the Schedule E category catalog (design Property 14).

Property 14 states that *no user-assignable category maps to the depreciation
line* (Schedule E Part I, Line 18). Depreciation on the report is derived from
the depreciation schedules, never from a user-assigned transaction category, so
Line 18 must be absent from the assignable catalog.

The catalog itself is fixed reference data, so the property is exercised by
generating arbitrary Schedule E line numbers ("assignment attempts") and
asserting the assignability invariant holds for every drawn value: a line is
assignable *iff* it is one of the expected income/expense lines, and Line 18 is
never assignable. This turns a fixed-data claim into a universally-quantified
property over the full space of possible line numbers.

Validates: Requirements 7.5
"""

from __future__ import annotations

import boto3
from hypothesis import given
from hypothesis import strategies as st
from moto import mock_aws

from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.category import (
    CATEGORY_CATALOG,
    list_categories,
    seed_categories,
)

TABLE_NAME = "Logstead"

# The complete set of Schedule E lines the catalog is allowed to expose:
# income lines 3-4 and expense lines 5-17 plus Other (19). Line 18
# (Depreciation) is intentionally excluded (Requirement 7.5).
_EXPECTED_INCOME_LINES = {3, 4}
_EXPECTED_EXPENSE_LINES = {5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 19}
_EXPECTED_LINES = _EXPECTED_INCOME_LINES | _EXPECTED_EXPENSE_LINES

_DEPRECIATION_LINE = 18


def _assignable_lines() -> frozenset[int]:
    """The set of Schedule E lines exposed by the assignable catalog."""
    return frozenset(c.schedule_e_line for c in CATEGORY_CATALOG)


def _schedule_e_line_attempts() -> st.SearchStrategy[int]:
    """Generate arbitrary Schedule E line numbers to treat as assignment attempts.

    The strategy mixes two sources so the space is both focused and large enough
    to run the required minimum of 100 examples:

    * A weighted draw from the Schedule E Part I line range (0-30) so every
      valid income/expense line and, crucially, the depreciation line (18) are
      hit frequently.
    * Arbitrary integers (including negatives and large values) that must never
      be assignable, covering the out-of-range space.
    """
    focused = st.integers(min_value=0, max_value=30)
    wide = st.integers()
    return st.one_of(focused, wide)


# Feature: logstead, Property 14: No assignable category maps to the depreciation line
@given(line=_schedule_e_line_attempts())
def test_no_assignable_category_maps_to_depreciation_line(line: int) -> None:
    assignable = _assignable_lines()

    # Core invariant: the depreciation line is never assignable, whatever the
    # generated attempt happens to be.
    assert _DEPRECIATION_LINE not in assignable

    # A drawn line is assignable exactly when it is one of the expected
    # income/expense lines -- which, by construction, excludes Line 18.
    assert (line in assignable) == (line in _EXPECTED_LINES)

    # In particular, no attempt to treat the depreciation line as assignable
    # can ever succeed.
    if line == _DEPRECIATION_LINE:
        assert line not in assignable


def test_seeded_catalog_excludes_depreciation_line() -> None:
    """The seeded + listed catalog exposes only expected lines, never Line 18.

    This checks the persistence path (seed -> list) upholds the same
    assignability invariant as the in-memory catalog: the round-tripped catalog
    exposes exactly the expected income/expense lines and never the depreciation
    line, and no drawn line number outside the expected set is assignable.
    """
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        repo = DynamoRepository(client, TABLE_NAME)
        seed_categories(repo)
        listed_lines = frozenset(c.schedule_e_line for c in list_categories(repo))

    assert listed_lines == _EXPECTED_LINES
    assert _DEPRECIATION_LINE not in listed_lines
    for line in range(0, 31):
        assert (line in listed_lines) == (line in _EXPECTED_LINES)
