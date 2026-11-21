"""Unit tests for the imported marker round-trip (task 1.3).

These protect backward compatibility of the ``imported`` marker added for
Schedule E Import (Req 7.1, 7.2, 7.5):

* the marker survives the serialization boundary
  (``_from_item(transaction_to_item(txn)).imported == txn.imported``) for both
  ``True`` and ``False``;
* a stored item that predates the feature (no ``imported`` attribute) reads back
  as ``imported=False`` — the key backward-compatibility guarantee for every
  pre-existing transaction;
* an ordinary ``TransactionService.create`` yields ``imported=False``.

The round-trip assertions are pure functions of the serialization helpers and
need no AWS; the ``create`` assertion runs against ``moto``-backed DynamoDB and
S3 using the same fixture pattern as ``test_transaction_service.py``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.transaction import Transaction, TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.transaction import (
    TransactionService,
    _from_item,
    transaction_to_item,
)

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
PROPERTY_ID = "prop-1"


def _txn(imported: bool) -> Transaction:
    return Transaction(
        id="txn-1",
        property_id=PROPERTY_ID,
        date="2024-04-15",
        amount=Decimal("1750.00"),
        type="income",
        category_id="rents-received",
        schedule_e_line=3,
        description=None,
        created_at="2024-04-15T00:00:00+00:00",
        updated_at="2024-04-15T00:00:00+00:00",
        imported=imported,
    )


# --- Round-trip preserves the marker (Req 7.1, 7.5) --------------------------


@pytest.mark.parametrize("imported", [True, False])
def test_imported_round_trips_through_serialization(imported: bool):
    txn = _txn(imported)

    restored = _from_item(transaction_to_item(txn, date.fromisoformat(txn.date)))

    assert restored.imported is imported
    assert restored.imported == txn.imported


# --- Legacy items (no attribute) default to False (Req 7.2) ------------------


def test_item_without_imported_reads_back_false():
    # Simulate a transaction written before the feature existed.
    item = transaction_to_item(_txn(True), date(2024, 4, 15))
    del item["imported"]

    restored = _from_item(item)

    assert restored.imported is False


# --- Ordinary create is never marked imported (Req 7.2) ----------------------


@pytest.fixture
def aws():
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
        yield ddb, s3


@pytest.fixture
def service(aws):
    ddb, s3 = aws
    return TransactionService(
        DynamoRepository(ddb, TABLE_NAME), S3FileAdapter(s3, BUCKET)
    )


def test_ordinary_create_is_not_imported(service):
    created = service.create(
        TransactionInput(
            property_id=PROPERTY_ID,
            date="2024-04-15",
            amount=Decimal("1750.00"),
            type="income",
            category_id="rents-received",
            description=None,
        )
    )

    assert created.is_ok
    assert created.value.imported is False

    # And it survives the read path too.
    got = service.get(PROPERTY_ID, created.value.id)
    assert got.is_ok
    assert got.value.imported is False
