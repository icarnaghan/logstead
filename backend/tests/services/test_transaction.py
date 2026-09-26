"""Verification for the Transaction Service (task 10.1, Requirements 5, 7).

Exercises the service against a ``moto``-backed DynamoDB table (with the GSI2
tax-year index) **and** S3 bucket so no live AWS call is made and both
collaborators are real. Coverage mirrors the task's acceptance criteria:

* create success + Schedule E line recorded from the category (5.1, 7.3);
* create validation: missing fields (5.3), amount <= 0 (5.2), Other requires a
  description (7.4), unknown category;
* list is date-descending (5.4) and excludes receipt rows;
* list_by_tax_year returns exactly in-year transactions via GSI2 (5.5);
* update saves edits (5.6) including a date change that moves the sort key;
* delete removes the transaction and its receipts (5.7, 5.8);
* receipts attach/list/delete against S3 + metadata (5.8).

The Property-based tests (10.2-10.6) and the unit happy-path task (10.7) are
intentionally not implemented here.
"""

from __future__ import annotations

from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.transaction import TransactionInput
from logstead.repository import keys
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
def repo(aws):
    ddb, _ = aws
    return DynamoRepository(ddb, TABLE_NAME)


@pytest.fixture
def s3_client(aws):
    _, s3 = aws
    return s3


@pytest.fixture
def service(repo, s3_client):
    return TransactionService(repo, S3FileAdapter(s3_client, BUCKET))


def _income(date_str: str, amount: str = "1000.00") -> TransactionInput:
    return TransactionInput(
        property_id=PROPERTY_ID,
        date=date_str,
        amount=Decimal(amount),
        type="income",
        category_id="rents-received",
        description=None,
    )


# --- Create + Schedule E line recorded (Requirements 5.1, 7.3) ---------------


def test_create_success_records_schedule_e_line(service, repo):
    result = service.create(_income("2024-03-07", "1500.00"))

    assert result.is_ok
    txn = result.value
    assert txn.id
    assert txn.property_id == PROPERTY_ID
    assert txn.amount == Decimal("1500.00")
    assert txn.type == "income"
    assert txn.category_id == "rents-received"
    # Line recorded from the category (Rents received -> Line 3).
    assert txn.schedule_e_line == 3

    # Persisted with base-table and GSI2 keys; amount stored as money string.
    d = keys.from_yyyymmdd(20240307)
    stored = repo.get_item(
        keys.property_scoped_pk(PROPERTY_ID), keys.transaction_sk(d, txn.id)
    )
    assert stored is not None
    assert stored["scheduleELine"] == 3
    assert stored["amount"] == Decimal("1500.00")
    assert stored["GSI2PK"] == keys.gsi2_year_pk(PROPERTY_ID, 2024)


def test_create_expense_records_its_line(service):
    result = service.create(
        TransactionInput(
            property_id=PROPERTY_ID,
            date="2024-05-01",
            amount=Decimal("250.00"),
            type="expense",
            category_id="repairs",
            description=None,
        )
    )
    assert result.is_ok
    assert result.value.schedule_e_line == 14  # Repairs -> Line 14


# --- Create validation (Requirements 5.2, 5.3, 7.4) --------------------------


@pytest.mark.parametrize(
    "field,mutate",
    [
        ("property_id", {"property_id": None}),
        ("date", {"date": None}),
        ("amount", {"amount": None}),
        ("category_id", {"category_id": None}),
    ],
)
def test_create_rejects_missing_fields(service, field, mutate):
    base = _income("2024-03-07")
    data = TransactionInput(
        property_id=mutate.get("property_id", base.property_id),
        date=mutate.get("date", base.date),
        amount=mutate.get("amount", base.amount),
        type=base.type,
        category_id=mutate.get("category_id", base.category_id),
        description=base.description,
    )
    result = service.create(data)
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == field


@pytest.mark.parametrize("bad", ["0.00", "-5.00"])
def test_create_rejects_non_positive_amount(service, bad):
    result = service.create(_income("2024-03-07", bad))
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "amount"


def test_create_rejects_bad_date(service):
    result = service.create(_income("not-a-date"))
    assert not result.is_ok
    assert result.error.field == "date"


def test_create_rejects_unknown_category(service):
    data = TransactionInput(
        property_id=PROPERTY_ID,
        date="2024-03-07",
        amount=Decimal("10.00"),
        type="expense",
        category_id="nope",
        description=None,
    )
    result = service.create(data)
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "category_id"


def test_other_category_requires_description(service):
    data = TransactionInput(
        property_id=PROPERTY_ID,
        date="2024-03-07",
        amount=Decimal("42.00"),
        type="expense",
        category_id="other",
        description="   ",  # blank -> treated as missing
    )
    result = service.create(data)
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "description"

    # With a description it succeeds and records Line 19.
    ok = service.create(
        TransactionInput(
            property_id=PROPERTY_ID,
            date="2024-03-07",
            amount=Decimal("42.00"),
            type="expense",
            category_id="other",
            description="Bank fee",
        )
    )
    assert ok.is_ok
    assert ok.value.schedule_e_line == 19
    assert ok.value.description == "Bank fee"


# --- List date-descending (Requirement 5.4) ---------------------------------


def test_list_is_date_descending_and_excludes_receipts(service):
    service.create(_income("2024-01-15"))
    service.create(_income("2024-12-31"))
    service.create(_income("2024-06-01"))

    listed = service.list_for_property(PROPERTY_ID)
    assert listed.is_ok
    dates = [t.date for t in listed.value]
    assert dates == ["2024-12-31", "2024-06-01", "2024-01-15"]

    # Attaching a receipt must not add a row to the transaction listing.
    target = listed.value[0]
    service.attach_receipt(PROPERTY_ID, target.id, "receipt.pdf", "application/pdf")
    again = service.list_for_property(PROPERTY_ID)
    assert len(again.value) == 3


# --- Tax-year filtering (Requirement 5.5) ------------------------------------


def test_list_by_tax_year_returns_exactly_in_year(service):
    service.create(_income("2023-12-31"))
    service.create(_income("2024-01-01"))
    service.create(_income("2024-07-04"))
    service.create(_income("2024-12-31"))
    service.create(_income("2025-01-01"))

    result = service.list_for_property(PROPERTY_ID, tax_year=2024)
    assert result.is_ok
    dates = [t.date for t in result.value]
    # Exactly the three 2024 dates, newest-first.
    assert dates == ["2024-12-31", "2024-07-04", "2024-01-01"]


# --- Get / Update incl. date-change key move (Requirement 5.6) ---------------


def test_get_returns_transaction_and_not_found(service):
    created = service.create(_income("2024-03-07")).value
    got = service.get(PROPERTY_ID, created.id)
    assert got.is_ok
    assert got.value.id == created.id

    missing = service.get(PROPERTY_ID, "nope")
    assert not missing.is_ok
    assert missing.error.kind == "not_found"


def test_update_saves_edits_without_date_change(service):
    created = service.create(_income("2024-03-07", "1000.00")).value
    result = service.update(
        PROPERTY_ID,
        created.id,
        TransactionInput(
            property_id=PROPERTY_ID,
            date="2024-03-07",
            amount=Decimal("1234.56"),
            type="expense",
            category_id="utilities",
            description=None,
        ),
    )
    assert result.is_ok
    assert result.value.id == created.id
    assert result.value.amount == Decimal("1234.56")
    assert result.value.schedule_e_line == 17  # Utilities

    # Single row still (id preserved, same sort key).
    listed = service.list_for_property(PROPERTY_ID)
    assert len(listed.value) == 1
    assert listed.value[0].amount == Decimal("1234.56")


def test_update_with_date_change_moves_sort_key(service, repo):
    created = service.create(_income("2024-03-07", "1000.00")).value
    old_d = keys.from_yyyymmdd(20240307)
    old_sk = keys.transaction_sk(old_d, created.id)

    result = service.update(
        PROPERTY_ID,
        created.id,
        TransactionInput(
            property_id=PROPERTY_ID,
            date="2024-09-09",
            amount=Decimal("1000.00"),
            type="income",
            category_id="rents-received",
            description=None,
        ),
    )
    assert result.is_ok
    assert result.value.date == "2024-09-09"
    assert result.value.id == created.id

    # Old sort-key row is gone; a new one exists under the new date.
    assert repo.get_item(keys.property_scoped_pk(PROPERTY_ID), old_sk) is None
    new_d = keys.from_yyyymmdd(20240909)
    new_sk = keys.transaction_sk(new_d, created.id)
    assert repo.get_item(keys.property_scoped_pk(PROPERTY_ID), new_sk) is not None

    # Still exactly one transaction, and the GSI2 tax-year query still finds it.
    listed = service.list_for_property(PROPERTY_ID)
    assert len(listed.value) == 1
    by_year = service.list_for_property(PROPERTY_ID, tax_year=2024)
    assert [t.id for t in by_year.value] == [created.id]


def test_update_revalidates(service):
    created = service.create(_income("2024-03-07")).value
    bad = service.update(
        PROPERTY_ID,
        created.id,
        TransactionInput(
            property_id=PROPERTY_ID,
            date="2024-03-07",
            amount=Decimal("-1.00"),
            type="income",
            category_id="rents-received",
            description=None,
        ),
    )
    assert not bad.is_ok
    assert bad.error.field == "amount"


def test_update_unknown_is_not_found(service):
    result = service.update(PROPERTY_ID, "nope", _income("2024-03-07"))
    assert not result.is_ok
    assert result.error.kind == "not_found"


# --- Delete (Requirement 5.7) + receipts cascade (5.8) -----------------------


def test_delete_removes_transaction_and_receipts(service, repo, s3_client):
    created = service.create(_income("2024-03-07")).value
    attached = service.attach_receipt(
        PROPERTY_ID, created.id, "r.pdf", "application/pdf"
    ).value
    # Simulate the browser completing the upload.
    s3_client.put_object(
        Bucket=BUCKET, Key=attached.document.s3_key, Body=b"x",
        ContentType="application/pdf",
    )

    deleted = service.delete(PROPERTY_ID, created.id)
    assert deleted.is_ok

    # Transaction gone.
    assert service.get(PROPERTY_ID, created.id).is_ok is False
    assert service.list_for_property(PROPERTY_ID).value == []

    # Receipt metadata gone and S3 object gone.
    receipts = service.list_receipts(PROPERTY_ID, created.id)
    assert not receipts.is_ok  # transaction no longer exists
    contents = s3_client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    assert not any(o["Key"] == attached.document.s3_key for o in contents)


def test_delete_unknown_is_not_found(service):
    result = service.delete(PROPERTY_ID, "nope")
    assert not result.is_ok
    assert result.error.kind == "not_found"


# --- Receipts attach / list / delete (Requirement 5.8) -----------------------


def test_attach_list_delete_receipt(service, repo, s3_client):
    created = service.create(_income("2024-03-07")).value

    attached = service.attach_receipt(
        PROPERTY_ID, created.id, "invoice.pdf", "application/pdf"
    )
    assert attached.is_ok
    up = attached.value
    assert up.upload_url.startswith("https://")
    assert BUCKET in up.upload_url
    assert up.document.transaction_id == created.id
    assert up.document.s3_key.startswith(f"receipts/{created.id}/")

    listed = service.list_receipts(PROPERTY_ID, created.id)
    assert listed.is_ok
    assert len(listed.value) == 1
    assert listed.value[0].document.id == up.document.id
    assert listed.value[0].download_url.startswith("https://")

    s3_client.put_object(
        Bucket=BUCKET, Key=up.document.s3_key, Body=b"x",
        ContentType="application/pdf",
    )
    removed = service.delete_receipt(PROPERTY_ID, created.id, up.document.id)
    assert removed.is_ok
    assert service.list_receipts(PROPERTY_ID, created.id).value == []
    contents = s3_client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    assert not any(o["Key"] == up.document.s3_key for o in contents)


def test_attach_receipt_unknown_transaction_is_not_found(service):
    result = service.attach_receipt(PROPERTY_ID, "nope", "r.pdf", "application/pdf")
    assert not result.is_ok
    assert result.error.kind == "not_found"


def test_delete_receipt_unknown_is_not_found(service):
    created = service.create(_income("2024-03-07")).value
    result = service.delete_receipt(PROPERTY_ID, created.id, "nope")
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "document_id"
