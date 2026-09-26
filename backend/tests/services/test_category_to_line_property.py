# Feature: logstead, Property 13: Category assignment records the correct Schedule E line
"""Property test for task 10.5 — category assignment records the Schedule E line.

Property 13 (design.md): *For any* user-assignable Transaction_Category,
assigning it to a transaction records the Schedule E line defined for that
category in the fixed catalog.

Validates: Requirements 7.1, 7.2, 7.3

Strategy
--------
We draw a category from :data:`CATEGORY_CATALOG` (every assignable category,
income + expense — the depreciation Line 18 is intentionally absent from the
catalog) and build a valid :class:`TransactionInput` for it:

* ``type`` matches the category ``kind`` (income categories -> ``"income"``,
  expense -> ``"expense"``) so type validation passes;
* a non-blank description is supplied whenever the category
  ``requires_description`` (the Other category, Line 19) so it does not fail
  validation;
* ``date`` and ``amount`` are drawn as valid values (a real ISO date and a
  strictly-positive two-decimal amount).

For each draw we ``create`` the transaction and assert
``result.value.schedule_e_line == category.schedule_e_line``. We also assert the
line round-trips: both ``get`` and ``list_for_property`` report the same
Schedule E line for the created transaction.

Because the catalog has ~16 categories and we draw a category per example, at
>=150 examples every category is exercised many times. A single moto-backed
table + S3 bucket is shared across the draws (module-scoped): each transaction
uses a fresh id and a unique per-example property partition so state never
bleeds between examples.
"""

from __future__ import annotations

import itertools
from datetime import date
from decimal import Decimal

import boto3
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.category import CATEGORY_CATALOG
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"


@pytest.fixture(scope="module")
def service():
    """A TransactionService over a moto-backed table (base + GSI2) and S3.

    Module-scoped so the ~150 Hypothesis examples share one set of AWS
    resources; each example writes under its own property partition and a fresh
    transaction id, so no state leaks between draws.
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


# A unique property id per example keeps each draw in its own partition.
_property_counter = itertools.count()

# Every assignable category in the fixed catalog (income + expense, incl. Other).
_categories = st.sampled_from(CATEGORY_CATALOG)

# A valid ISO date string.
_dates = st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31)).map(
    lambda d: d.isoformat()
)

# Strictly-positive two-decimal amounts.
_amounts = st.integers(min_value=1, max_value=100_000_000).map(
    lambda cents: Decimal(cents) / Decimal(100)
)

# Free-text descriptions (non-blank so Other's requires-description passes).
_descriptions = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=1, max_size=40
)


@settings(
    deadline=None,
    max_examples=150,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(category=_categories, date_str=_dates, amount=_amounts, description=_descriptions)
def test_category_assignment_records_schedule_e_line(
    service, category, date_str, amount, description
):
    """A created transaction records its category's Schedule E line (7.3)."""
    property_id = f"prop-{next(_property_counter)}"

    data = TransactionInput(
        property_id=property_id,
        date=date_str,
        amount=amount,
        # Type must match the category kind so type validation passes.
        type=category.kind,
        category_id=category.id,
        # Supply a description; required for Other (Line 19), harmless otherwise.
        description=description if category.requires_description else None,
    )

    result = service.create(data)

    assert result.is_ok, (
        f"create failed for {category.id!r}: "
        f"{None if result.is_ok else result.error.message}"
    )
    txn = result.value

    # The core property: the recorded line equals the catalog line.
    assert txn.schedule_e_line == category.schedule_e_line

    # Round-trip: get() reports the same line.
    got = service.get(property_id, txn.id)
    assert got.is_ok
    assert got.value.schedule_e_line == category.schedule_e_line

    # Round-trip: list_for_property() reports the same line for this txn.
    listed = service.list_for_property(property_id)
    assert listed.is_ok
    matching = [t for t in listed.value if t.id == txn.id]
    assert len(matching) == 1
    assert matching[0].schedule_e_line == category.schedule_e_line
