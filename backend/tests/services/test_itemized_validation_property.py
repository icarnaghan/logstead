"""Property-based tests for itemized validation (design Properties 10, 11, 12).

* Property 10: the itemized marker cannot be changed through ``update``.
* Property 11: only configured expense categories accept itemized entries.
* Property 12: an entry date must fall in the stated tax year (exercised
  through ``ItemizedExpenseService.create_entry``).

All run against a moto-backed repository.

**Validates: Requirements 2.6, 2.12, 10.5, 11.2, 11.4**
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.category import CATEGORY_CATALOG
from logstead.services.itemized import (
    ITEMIZED_CATEGORIES,
    EntryInput,
    ItemizedExpenseService,
)
from logstead.services.transaction import TransactionService

REGION = "us-east-1"
TABLE_NAME = "logstead-itemized-validation-test"
BUCKET = "logstead-itemized-validation-test"

_MAX_EXAMPLES = 100

_DATES = st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 12, 31))
_AMOUNTS = st.integers(min_value=1, max_value=99_999_999).map(
    lambda cents: Decimal(cents).scaleb(-2)
)
_DESCRIPTIONS = st.text(alphabet="abcdefg hij", min_size=1, max_size=40).filter(
    lambda s: s.strip() != ""
)
_ITEMIZED_ID = next(iter(ITEMIZED_CATEGORIES))


@pytest.fixture(scope="module")
def services():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": name,
                    "KeySchema": [
                        {"AttributeName": f"{name}PK", "KeyType": "HASH"},
                        {"AttributeName": f"{name}SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
                for name in ("GSI1", "GSI2")
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        txns = TransactionService(
            DynamoRepository(ddb, TABLE_NAME), S3FileAdapter(s3, BUCKET)
        )
        yield txns, ItemizedExpenseService(txns)


def _stored(txns: TransactionService, property_id: str):
    listed = txns.list_for_property(property_id)
    assert listed.is_ok
    return listed.value


# Feature: itemized-expenses, Property 10: The itemized marker is immutable through updates
@settings(max_examples=_MAX_EXAMPLES, deadline=None)
@given(
    start_itemized=st.booleans(),
    claim_itemized=st.booleans(),
    created_date=_DATES,
    created_amount=_AMOUNTS,
    new_date=_DATES,
    new_amount=_AMOUNTS,
    description=_DESCRIPTIONS,
)
def test_itemized_marker_immutable_through_update(
    services,
    start_itemized: bool,
    claim_itemized: bool,
    created_date: date,
    created_amount: Decimal,
    new_date: date,
    new_amount: Decimal,
    description: str,
) -> None:
    txns, _ = services
    property_id = str(uuid.uuid4())
    created = txns.create(
        TransactionInput(
            property_id=property_id,
            date=created_date.isoformat(),
            amount=created_amount,
            type="expense",
            category_id=_ITEMIZED_ID,
            description=description,
            itemized=start_itemized,
        )
    )
    assert created.is_ok, created.error
    before = txns.get(property_id, created.value.id).value

    result = txns.update(
        property_id,
        created.value.id,
        TransactionInput(
            property_id=property_id,
            date=new_date.isoformat(),
            amount=new_amount,
            type="expense",
            category_id=_ITEMIZED_ID,
            description=description,
            itemized=claim_itemized,
        ),
    )
    after = txns.get(property_id, created.value.id).value

    if claim_itemized != start_itemized:
        assert not result.is_ok
        assert result.error.kind == "validation"
        assert result.error.field == "itemized"
        assert after == before
    else:
        assert result.is_ok, result.error
        assert result.value.itemized is start_itemized
        assert after.itemized is start_itemized
        assert after.amount == new_amount
        assert after.date == new_date.isoformat()
    assert len(_stored(txns, property_id)) == 1


# Feature: itemized-expenses, Property 11: Only configured categories accept itemized entries
@settings(max_examples=_MAX_EXAMPLES, deadline=None)
@given(
    category=st.sampled_from(CATEGORY_CATALOG),
    entry_date=_DATES,
    amount=_AMOUNTS,
    description=_DESCRIPTIONS,
    txn_type=st.sampled_from(["income", "expense"]),
)
def test_only_configured_expense_categories_accept_itemized(
    services,
    category,
    entry_date: date,
    amount: Decimal,
    description: str,
    txn_type: str,
) -> None:
    txns, items = services

    # Through the entry service the type is always expense.
    property_id = str(uuid.uuid4())
    created = items.create_entry(
        property_id,
        category.id,
        EntryInput(
            date=entry_date.isoformat(), amount=amount, description=description
        ),
    )
    configured = category.id in ITEMIZED_CATEGORIES and category.kind == "expense"
    if configured:
        assert created.is_ok, created.error
        assert created.value.itemized is True
        assert len(_stored(txns, property_id)) == 1
    else:
        assert not created.is_ok
        assert created.error.kind == "validation"
        assert created.error.field in ("category_id", "itemized")
        assert _stored(txns, property_id) == []

    # Directly through the transaction service the type varies as well.
    property_id = str(uuid.uuid4())
    direct = txns.create(
        TransactionInput(
            property_id=property_id,
            date=entry_date.isoformat(),
            amount=amount,
            type=txn_type,  # type: ignore[arg-type]
            category_id=category.id,
            description=description,
            itemized=True,
        )
    )
    accepted = (
        category.id in ITEMIZED_CATEGORIES and txn_type == "expense"
    )
    if accepted:
        assert direct.is_ok, direct.error
        assert len(_stored(txns, property_id)) == 1
    else:
        assert not direct.is_ok
        assert direct.error.kind == "validation"
        assert direct.error.field in ("category_id", "itemized", "type")
        assert _stored(txns, property_id) == []


# Feature: itemized-expenses, Property 12: Entry date must fall in the stated tax year
@settings(max_examples=_MAX_EXAMPLES, deadline=None)
@given(
    entry_date=_DATES,
    other_year=st.integers(min_value=2000, max_value=2099),
    use_matching_year=st.booleans(),
    amount=_AMOUNTS,
    description=_DESCRIPTIONS,
)
def test_entry_date_must_fall_in_tax_year(
    services,
    entry_date: date,
    other_year: int,
    use_matching_year: bool,
    amount: Decimal,
    description: str,
) -> None:
    txns, items = services
    property_id = str(uuid.uuid4())
    tax_year = entry_date.year if use_matching_year else other_year

    result = items.create_entry(
        property_id,
        _ITEMIZED_ID,
        EntryInput(
            date=entry_date.isoformat(),
            amount=amount,
            description=description,
            tax_year=tax_year,
        ),
    )

    if entry_date.year == tax_year:
        assert result.is_ok, result.error
        assert result.value.date == entry_date.isoformat()
        assert len(_stored(txns, property_id)) == 1
    else:
        assert not result.is_ok
        assert result.error.kind == "validation"
        assert result.error.field == "date"
        assert _stored(txns, property_id) == []
