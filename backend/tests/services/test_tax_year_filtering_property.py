"""Property-based test: the tax-year filter returns exactly in-year transactions.

Design Property 9 (Requirement 5.5): *for any* set of transactions and any tax
year, the filtered listing contains exactly those transactions whose date falls
within that tax year.

``TransactionService.list_for_property(property_id, tax_year=Y)`` queries the
GSI2 tax-year partition (``GSI2PK = PROPERTY#<id>#YEAR#<Y>``) rather than
scanning the base table. This property drives that behaviour universally: it
generates transactions with dates spanning several years (deliberately including
year-boundary dates such as Jan 1 and Dec 31), creates them, then for a chosen
target year asserts that the filtered result contains exactly the transactions
whose ``date.year == Y`` (compared as id sets), that the filtered set is a subset
of the full unfiltered listing, and that the union of all per-year filters
reconstructs the full set with no leakage across years.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(with the GSI2 tax-year index the service relies on) plus an S3 bucket needed to
construct the ``S3FileAdapter``, mirroring the fixture pattern in
``test_transaction.py``. Per-example provisioning is not instantaneous, so the
deadline is disabled; the example count is held at >= 100.
"""

from __future__ import annotations

import contextlib
from datetime import date
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
PROPERTY_ID = "prop-1"
# A valid, known, non-Other income category so the description rule and the
# unknown-category path never confound this property (Line 3, Rents received).
CATEGORY_ID = "rents-received"


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI2) and S3 bucket.

    Yields a :class:`TransactionService` bound to freshly created resources so
    each Hypothesis example runs against a clean store.
    """
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        yield TransactionService(
            DynamoRepository(ddb, TABLE_NAME), S3FileAdapter(s3, BUCKET)
        )


# --- Date strategy ------------------------------------------------------------
#
# Dates are drawn across a few adjacent years so a target year has both in-year
# and out-of-year siblings. Year-boundary dates (Jan 1 / Dec 31) are explicitly
# mixed in so the filter's year classification is exercised at the edges where
# an off-by-one would leak a neighbouring year's transactions.
_YEARS = (2022, 2023, 2024, 2025)

_boundary_dates = st.sampled_from(
    [date(y, m, d) for y in _YEARS for (m, d) in ((1, 1), (12, 31))]
)
_interior_dates = st.builds(
    date,
    year=st.sampled_from(_YEARS),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
)
# Bias toward boundary dates so most examples stress the year edges.
_dates = st.one_of(_boundary_dates, _boundary_dates, _interior_dates)

_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


# Feature: logstead, Property 9: Tax-year filter returns exactly in-year transactions
@settings(deadline=None, max_examples=150)
@given(
    entries=st.lists(
        st.tuples(_dates, _amounts), min_size=1, max_size=25
    ),
    target_index=st.integers(min_value=0),
)
def test_tax_year_filter_returns_exactly_in_year_transactions(
    entries: list[tuple[date, Decimal]],
    target_index: int,
) -> None:
    """Filtering by year Y returns exactly the transactions dated in year Y.

    Validates: Requirement 5.5
    """
    with _moto_service() as service:
        # Create every generated transaction, remembering each id's year.
        year_by_id: dict[str, int] = {}
        for d, amount in entries:
            created = service.create(
                TransactionInput(
                    property_id=PROPERTY_ID,
                    date=d.isoformat(),
                    amount=amount,
                    type="income",
                    category_id=CATEGORY_ID,
                    description=None,
                )
            )
            assert created.is_ok, f"unexpected create failure for {d} {amount}"
            year_by_id[created.value.id] = d.year

        all_ids = set(year_by_id)
        years_present = sorted({d.year for d, _ in entries})

        # The full (unfiltered) listing must contain exactly the created ids.
        full = service.list_for_property(PROPERTY_ID)
        assert full.is_ok
        full_ids = {t.id for t in full.value}
        assert full_ids == all_ids

        # Pick a target year deterministically from a present year.
        target_year = years_present[target_index % len(years_present)]
        expected_ids = {
            tid for tid, y in year_by_id.items() if y == target_year
        }

        filtered = service.list_for_property(PROPERTY_ID, tax_year=target_year)
        assert filtered.is_ok
        filtered_ids = {t.id for t in filtered.value}

        # Exactly the in-year transactions -- no misses, no leakage.
        assert filtered_ids == expected_ids, (
            f"year={target_year} expected {expected_ids} got {filtered_ids}"
        )
        # Every returned transaction is genuinely dated in the target year.
        for t in filtered.value:
            assert date.fromisoformat(t.date).year == target_year
        # The filtered set is a subset of the full unfiltered listing.
        assert filtered_ids <= full_ids

        # A year with no transactions returns nothing (no cross-year bleed).
        empty_year = max(_YEARS) + 5
        assert empty_year not in years_present
        empty = service.list_for_property(PROPERTY_ID, tax_year=empty_year)
        assert empty.is_ok
        assert empty.value == []

        # The union of every per-year filter reconstructs the full set exactly,
        # and the per-year partitions are disjoint (each id in exactly one year).
        union_ids: set[str] = set()
        total = 0
        for y in years_present:
            year_ids = {
                t.id for t in service.list_for_property(PROPERTY_ID, tax_year=y).value
            }
            assert union_ids.isdisjoint(year_ids), f"year {y} overlaps another year"
            union_ids |= year_ids
            total += len(year_ids)
        assert union_ids == all_ids
        assert total == len(all_ids)
