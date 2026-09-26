"""Happy-path unit tests for the Transaction Service (task 10.7).

These complement the broader verification suite in ``test_transaction.py``
(which also covers validation, tax-year filtering, and cascade deletes). Here we
focus purely on the *happy paths* of the CRUD + receipts surface, and add
angles the verification file does not exercise, such as:

* create records id, both timestamps, and the category's Schedule E line, and
  the transaction is retrievable afterwards (Requirement 5.1);
* listing several transactions across many dates comes back newest-first,
  including a mix of income and expense categories (Requirement 5.4);
* an edit is visible through both ``get`` and ``list_for_property``
  (Requirement 5.6);
* delete removes the transaction from both ``get`` and the listing
  (Requirement 5.7);
* receipts: multiple receipts can be attached, each is listed with a download
  URL, and a single receipt can be removed leaving the rest (Requirement 5.8).

Everything runs against ``moto``-backed DynamoDB (with the GSI2 tax-year index)
and S3, using the same fixture pattern as ``test_transaction.py`` so both
collaborators are real and no live AWS call is made.
"""

from __future__ import annotations

from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
PROPERTY_ID = "prop-1"


@pytest.fixture
def aws():
    """A moto context with the table (base + GSI2) and S3 bucket pre-created."""
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
def s3_client(aws):
    _, s3 = aws
    return s3


@pytest.fixture
def service(aws, s3_client):
    ddb, _ = aws
    return TransactionService(
        DynamoRepository(ddb, TABLE_NAME), S3FileAdapter(s3_client, BUCKET)
    )


def _income(date_str: str, amount: str = "1000.00") -> TransactionInput:
    return TransactionInput(
        property_id=PROPERTY_ID,
        date=date_str,
        amount=Decimal(amount),
        type="income",
        category_id="rents-received",
        description=None,
    )


def _expense(
    date_str: str, amount: str = "250.00", category_id: str = "repairs"
) -> TransactionInput:
    return TransactionInput(
        property_id=PROPERTY_ID,
        date=date_str,
        amount=Decimal(amount),
        type="expense",
        category_id=category_id,
        description=None,
    )


# --- Create happy path (Requirement 5.1) -------------------------------------


def test_create_returns_populated_transaction_and_is_retrievable(service):
    result = service.create(_income("2024-04-15", "1750.00"))

    assert result.is_ok
    txn = result.value
    # Identity, association, and the recorded values are all present.
    assert txn.id
    assert txn.property_id == PROPERTY_ID
    assert txn.date == "2024-04-15"
    assert txn.amount == Decimal("1750.00")
    assert txn.type == "income"
    assert txn.category_id == "rents-received"
    # Schedule E line recorded from the category (Rents received -> Line 3).
    assert txn.schedule_e_line == 3
    # Both timestamps stamped on create.
    assert txn.created_at
    assert txn.updated_at
    assert txn.created_at == txn.updated_at

    # The created transaction is retrievable by id.
    got = service.get(PROPERTY_ID, txn.id)
    assert got.is_ok
    assert got.value.id == txn.id
    assert got.value.amount == Decimal("1750.00")


def test_create_expense_happy_path_records_its_line(service):
    result = service.create(_expense("2024-02-01", "320.50", "utilities"))

    assert result.is_ok
    txn = result.value
    assert txn.type == "expense"
    assert txn.category_id == "utilities"
    assert txn.amount == Decimal("320.50")
    assert txn.schedule_e_line == 17  # Utilities -> Line 17


# --- List newest-first across many dates (Requirement 5.4) -------------------


def test_list_returns_all_transactions_newest_first(service):
    # A mix of income and expense across several months, inserted out of order.
    service.create(_income("2024-03-10"))
    service.create(_expense("2024-11-22"))
    service.create(_income("2024-01-05"))
    service.create(_expense("2024-07-30", category_id="insurance"))
    service.create(_income("2024-09-14"))

    listed = service.list_for_property(PROPERTY_ID)
    assert listed.is_ok
    assert len(listed.value) == 5
    dates = [t.date for t in listed.value]
    assert dates == [
        "2024-11-22",
        "2024-09-14",
        "2024-07-30",
        "2024-03-10",
        "2024-01-05",
    ]
    # Both income and expense transactions appear in the same listing.
    types = {t.type for t in listed.value}
    assert types == {"income", "expense"}


# --- Update visible via get/list (Requirement 5.6) ---------------------------


def test_update_edits_are_visible_via_get_and_list(service):
    created = service.create(_income("2024-05-20", "1000.00")).value

    updated = service.update(
        PROPERTY_ID,
        created.id,
        _expense("2024-05-20", "425.75", "management-fees"),
    )
    assert updated.is_ok
    assert updated.value.id == created.id
    assert updated.value.type == "expense"
    assert updated.value.amount == Decimal("425.75")
    assert updated.value.category_id == "management-fees"
    assert updated.value.schedule_e_line == 11  # Management fees -> Line 11

    # The edit is visible through get.
    got = service.get(PROPERTY_ID, created.id)
    assert got.is_ok
    assert got.value.amount == Decimal("425.75")
    assert got.value.type == "expense"
    assert got.value.category_id == "management-fees"

    # And through the listing (still exactly one row, same id).
    listed = service.list_for_property(PROPERTY_ID)
    assert len(listed.value) == 1
    assert listed.value[0].id == created.id
    assert listed.value[0].amount == Decimal("425.75")


# --- Delete removes the transaction (Requirement 5.7) ------------------------


def test_delete_removes_transaction_from_get_and_list(service):
    keep = service.create(_income("2024-06-01")).value
    remove = service.create(_expense("2024-06-15")).value
    assert len(service.list_for_property(PROPERTY_ID).value) == 2

    deleted = service.delete(PROPERTY_ID, remove.id)
    assert deleted.is_ok

    # The deleted transaction is no longer retrievable.
    assert service.get(PROPERTY_ID, remove.id).is_ok is False
    # Only the untouched transaction remains in the listing.
    listed = service.list_for_property(PROPERTY_ID)
    assert [t.id for t in listed.value] == [keep.id]


# --- Receipts attach/list/delete (Requirement 5.8) ---------------------------


def test_attach_receipt_returns_upload_url_and_document(service):
    created = service.create(_income("2024-08-08")).value

    attached = service.attach_receipt(
        PROPERTY_ID, created.id, "invoice.pdf", "application/pdf"
    )
    assert attached.is_ok
    up = attached.value
    # A usable pre-signed PUT URL bound to this bucket.
    assert up.upload_url.startswith("https://")
    assert BUCKET in up.upload_url
    # Document metadata associates the receipt with its transaction.
    assert up.document.id
    assert up.document.transaction_id == created.id
    assert up.document.property_id == PROPERTY_ID
    assert up.document.original_filename == "invoice.pdf"
    assert up.document.content_type == "application/pdf"
    assert up.document.s3_key.startswith(f"receipts/{created.id}/")


def test_multiple_receipts_are_listed_with_download_urls(service):
    created = service.create(_income("2024-08-08")).value

    first = service.attach_receipt(
        PROPERTY_ID, created.id, "jan.pdf", "application/pdf"
    ).value
    second = service.attach_receipt(
        PROPERTY_ID, created.id, "feb.jpg", "image/jpeg"
    ).value

    listed = service.list_receipts(PROPERTY_ID, created.id)
    assert listed.is_ok
    assert len(listed.value) == 2
    listed_ids = {r.document.id for r in listed.value}
    assert listed_ids == {first.document.id, second.document.id}
    # Every listed receipt carries a pre-signed GET URL.
    for receipt in listed.value:
        assert receipt.download_url.startswith("https://")
        assert BUCKET in receipt.download_url


def test_delete_receipt_removes_only_the_target(service, s3_client):
    created = service.create(_income("2024-08-08")).value
    keep = service.attach_receipt(
        PROPERTY_ID, created.id, "keep.pdf", "application/pdf"
    ).value
    drop = service.attach_receipt(
        PROPERTY_ID, created.id, "drop.pdf", "application/pdf"
    ).value
    # Simulate the browser completing both uploads.
    for doc in (keep.document, drop.document):
        s3_client.put_object(
            Bucket=BUCKET, Key=doc.s3_key, Body=b"x", ContentType="application/pdf"
        )

    removed = service.delete_receipt(PROPERTY_ID, created.id, drop.document.id)
    assert removed.is_ok

    # Only the kept receipt remains in the listing and in S3.
    remaining = service.list_receipts(PROPERTY_ID, created.id)
    assert [r.document.id for r in remaining.value] == [keep.document.id]
    contents = s3_client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    keys_in_bucket = {o["Key"] for o in contents}
    assert keep.document.s3_key in keys_in_bucket
    assert drop.document.s3_key not in keys_in_bucket
