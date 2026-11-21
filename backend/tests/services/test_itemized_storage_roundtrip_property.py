"""Property-based test for transaction storage round trips (design Property 13).

* For any valid itemized entry, ``transaction_to_item`` written through the
  moto-backed repository and read back with ``_from_item`` is the identity,
  including ``itemized`` and ``notes``.
* For any transaction with default ``itemized`` and ``notes``, the stored item
  has neither attribute and equals the pre-feature item shape.
* Legacy stored items that lack ``itemized`` and ``notes`` read back with the
  defaults.

**Validates: Requirements 12.1, 12.2, 12.3**
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.transaction import Transaction
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.transaction import _from_item, transaction_to_item

REGION = "us-east-1"
TABLE_NAME = "logstead-itemized-roundtrip-test"

_MAX_EXAMPLES = 100

_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=200
)
_IDS = st.uuids().map(str)
_DATES = st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 12, 31))
_AMOUNTS = st.integers(min_value=1, max_value=99_999_999_99).map(
    lambda cents: Decimal(cents).scaleb(-2)
)
_TIMESTAMPS = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2099, 12, 31),
).map(lambda d: d.isoformat() + "Z")


@pytest.fixture(scope="module")
def repo():
    """A moto-backed repository with the base table and both GSIs."""
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
        yield DynamoRepository(ddb, TABLE_NAME)


@st.composite
def _transactions(draw: st.DrawFn, *, itemized: bool | None = None) -> Transaction:
    is_itemized = draw(st.booleans()) if itemized is None else itemized
    txn_date = draw(_DATES)
    return Transaction(
        id=draw(_IDS),
        property_id=draw(_IDS),
        date=txn_date.isoformat(),
        amount=draw(_AMOUNTS),
        type="expense" if is_itemized else draw(st.sampled_from(["income", "expense"])),
        category_id=draw(_TEXT),
        schedule_e_line=draw(st.integers(min_value=3, max_value=19)),
        description=draw(_TEXT) if is_itemized else draw(st.none() | _TEXT),
        created_at=draw(_TIMESTAMPS),
        updated_at=draw(_TIMESTAMPS),
        imported=False if is_itemized else draw(st.booleans()),
        itemized=is_itemized,
        notes=draw(st.none() | _TEXT) if is_itemized else None,
    )


def _store_and_read(repo: DynamoRepository, txn: Transaction) -> dict[str, Any]:
    item = transaction_to_item(txn, date.fromisoformat(txn.date))
    repo.put_item(item)
    stored = repo.get_item(str(item["PK"]), str(item["SK"]))
    assert stored is not None
    return stored


def _pre_feature_item(txn: Transaction) -> dict[str, Any]:
    """The item shape written before the itemized feature existed."""
    d = date.fromisoformat(txn.date)
    item: dict[str, Any] = {
        "PK": keys.property_scoped_pk(txn.property_id),
        "SK": keys.transaction_sk(d, txn.id),
        "GSI2PK": keys.gsi2_year_pk(txn.property_id, d.year),
        "GSI2SK": keys.gsi2_transaction_sk(d, txn.id),
        "id": txn.id,
        "propertyId": txn.property_id,
        "date": txn.date,
        "amount": txn.amount,
        "type": txn.type,
        "categoryId": txn.category_id,
        "scheduleELine": txn.schedule_e_line,
        "description": txn.description,
        "createdAt": txn.created_at,
        "updatedAt": txn.updated_at,
        "imported": txn.imported,
    }
    return {k: v for k, v in item.items() if v is not None}


# Feature: itemized-expenses, Property 13: Entry fields round-trip through storage
@settings(max_examples=_MAX_EXAMPLES, deadline=None)
@given(txn=_transactions(itemized=True))
def test_itemized_entry_round_trips(repo: DynamoRepository, txn: Transaction) -> None:
    stored = _store_and_read(repo, txn)

    assert stored["itemized"] is True
    assert ("notes" in stored) == (txn.notes is not None)
    assert _from_item(stored) == txn


# Feature: itemized-expenses, Property 13: Entry fields round-trip through storage
@settings(max_examples=_MAX_EXAMPLES, deadline=None)
@given(txn=_transactions(itemized=False))
def test_default_entry_matches_pre_feature_item_shape(
    repo: DynamoRepository, txn: Transaction
) -> None:
    assert txn.itemized is False and txn.notes is None

    stored = _store_and_read(repo, txn)

    assert "itemized" not in stored
    assert "notes" not in stored
    assert stored == _pre_feature_item(txn)
    assert _from_item(stored) == txn


# Feature: itemized-expenses, Property 13: Entry fields round-trip through storage
@settings(max_examples=_MAX_EXAMPLES, deadline=None)
@given(txn=_transactions(itemized=False))
def test_legacy_item_without_attributes_reads_defaults(
    repo: DynamoRepository, txn: Transaction
) -> None:
    legacy = _pre_feature_item(txn)
    legacy.pop("imported")  # items older than Schedule E Import also lack this
    repo.put_item(legacy)

    stored = repo.get_item(str(legacy["PK"]), str(legacy["SK"]))
    assert stored is not None
    restored = _from_item(stored)

    assert restored.itemized is False
    assert restored.notes is None
    assert restored.imported is False
    assert restored == Transaction(**{**txn.__dict__, "imported": False})
