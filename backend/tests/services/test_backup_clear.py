"""Example (ordering) tests for ``BackupService.clear`` (Requirements 8.3, 8.5).

Two safe-ordering guarantees clear must uphold, verified with recording fakes
that log every S3 delete and every DynamoDB row delete into one shared,
time-ordered event log:

* **8.3** (test_s3_delete_precedes_metadata_row_delete) — for every S3-backed
  record (photo, receipt), the ``delete_object`` call happens BEFORE the delete
  of that record's metadata row. A crash between the two then leaves at worst an
  orphaned metadata row pointing at an already-deleted (idempotent) key, never
  an orphaned S3 object.
* **8.5** (test_children_deleted_before_parent_property_row) — a property's
  child rows (transactions, assets, schedule rows, details, note, usage,
  photos, receipts) are deleted BEFORE the property's ``META`` mirror and its
  ``USER#/PROP#`` list row.

Data is seeded through the real services against moto DynamoDB (base + GSI1 +
GSI2) and moto S3 so the stored rows match production shape; clear then runs
against a repo wrapper + S3 fake that record ordering.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.depreciation import AssetInput
from logstead.models.property import PropertyDetails, PropertyInput, TaxAssessment
from logstead.models.transaction import TransactionInput
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.backup import BackupService
from logstead.services.depreciation import DepreciationService
from logstead.services.photo import PhotoService
from logstead.services.property import PropertyService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_ID = "user-1"


@pytest.fixture
def aws():
    """A moto context with the table (base + GSI1 + GSI2) and S3 bucket."""
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
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
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
def files(aws):
    _, s3 = aws
    return S3FileAdapter(s3, BUCKET)


@pytest.fixture
def user():
    return UserContext(user_id=USER_ID)


# --- Recording fakes that share one time-ordered event log -------------------


class RecordingS3:
    """Wraps a real S3 adapter, logging each delete into a shared event log.

    Substitutable for :class:`S3FileAdapter` in ``BackupService`` because clear
    only calls :meth:`delete_object`.
    """

    def __init__(self, inner: S3FileAdapter, log: list[tuple[str, str]]) -> None:
        self._inner = inner
        self._log = log

    def delete_object(self, key: str) -> None:  # type: ignore[override]
        self._log.append(("s3_delete", key))
        self._inner.delete_object(key)


class RecordingRepo:
    """Delegates to a real repo but logs every row-delete action in order.

    Only :meth:`transact_write` deletes are logged (that is how clear removes
    rows); reads and other writes pass straight through.
    """

    def __init__(self, inner: DynamoRepository, log: list[tuple[str, str]]) -> None:
        self._inner = inner
        self._log = log

    def transact_write(self, items: Any, *args: Any, **kwargs: Any) -> Any:
        for action in items:
            delete = action.get("delete") if isinstance(action, dict) else None
            if delete is not None:
                self._log.append(
                    ("row_delete", f"{delete['pk']}|{delete['sk']}")
                )
        return self._inner.transact_write(items, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        # Everything else (query, get_item, put_item, delete_item, …) delegates.
        return getattr(self._inner, name)


# --- Shared seeding: one property with binaries, txns, and an asset ----------


def _seed_full_property(repo, files, user) -> dict[str, Any]:
    """Seed one property with a note, usage, an income+expense txn (each with a
    receipt), an asset (materializing schedule rows), and a photo."""
    properties = PropertyService(repo, user)
    transactions = TransactionService(repo, files)
    depreciation = DepreciationService(repo)
    photos = PhotoService(repo, files)

    created = properties.create(
        PropertyInput(
            name="Maple Street Duplex",
            address_text="123 Maple St, Springfield, IL 62704",
            property_type="single_family",
            details=PropertyDetails(
                formatted_address="123 Maple St",
                latitude=Decimal("39.781721"),
                longitude=Decimal("-89.650148"),
                last_sale_price=Decimal("245000.00"),
                tax_assessments=[
                    TaxAssessment(year=2023, value=Decimal("230000.00"))
                ],
            ),
        )
    )
    assert created.is_ok
    prop = created.value

    assert properties.set_note(prop.id, "Tenant lease renews each August.").is_ok
    assert properties.set_usage_days(prop.id, 2023, 300, 0).is_ok

    receipt_keys: list[str] = []
    for date, amount, ttype, cat in (
        ("2024-03-01", Decimal("1850.00"), "income", "rents-received"),
        ("2024-04-15", Decimal("312.45"), "expense", "repairs"),
    ):
        txn = transactions.create(
            TransactionInput(
                property_id=prop.id,
                date=date,
                amount=amount,
                type=ttype,
                category_id=cat,
                description=None,
            )
        )
        assert txn.is_ok
        attached = transactions.attach_receipt(
            prop.id, txn.value.id, "receipt.pdf", "application/pdf"
        )
        assert attached.is_ok
        receipt_keys.append(attached.value.document.s3_key)

    asset = depreciation.create_asset(
        AssetInput(
            property_id=prop.id,
            description="HVAC system",
            cost_basis=Decimal("8000.00"),
            placed_in_service_date="2023-06-15",
            recovery_period_years=Decimal("27.5"),
        )
    )
    assert asset.is_ok

    upload = photos.request_upload(prop.id, "photo.jpg", "image/jpeg")
    assert upload.is_ok

    return {
        "property_id": prop.id,
        "photo_key": upload.value.photo.s3_key,
        "receipt_keys": receipt_keys,
    }


def _index(log: list[tuple[str, str]], predicate) -> int:
    for i, entry in enumerate(log):
        if predicate(entry):
            return i
    raise AssertionError(f"no log entry matched in {log}")


# --- Requirement 8.3: S3 delete before its metadata row delete ---------------


def test_s3_delete_precedes_metadata_row_delete(repo, files, user):
    seeded = _seed_full_property(repo, files, user)
    log: list[tuple[str, str]] = []

    recording_repo = RecordingRepo(repo, log)
    recording_s3 = RecordingS3(files, log)

    result = BackupService(recording_repo, recording_s3, user).clear()
    assert result.is_ok

    property_id = seeded["property_id"]
    pk = keys.property_scoped_pk(property_id)

    # Photo: its S3 delete precedes the delete of its metadata row.
    photo_key = seeded["photo_key"]
    photo_s3_idx = _index(log, lambda e: e == ("s3_delete", photo_key))
    photo_row_idx = _index(
        log,
        lambda e: e[0] == "row_delete"
        and e[1].startswith(f"{pk}|")
        and keys.PHOTO_PREFIX in e[1].split("|", 1)[1],
    )
    assert photo_s3_idx < photo_row_idx

    # Each receipt: its S3 delete precedes the delete of its DOC# metadata row.
    for receipt_key in seeded["receipt_keys"]:
        s3_idx = _index(log, lambda e, k=receipt_key: e == ("s3_delete", k))
        # There are multiple DOC rows; assert at least one DOC row-delete
        # occurs after this S3 delete and that no DOC row-delete precedes ANY
        # S3 delete of a receipt (checked in aggregate below).
        assert any(
            entry[0] == "row_delete"
            and keys.DOC_PREFIX in entry[1]
            and idx > s3_idx
            for idx, entry in enumerate(log)
        )

    # Aggregate guarantee: every S3 delete happens before every metadata-row
    # delete of an S3-backed (PHOTO#/#DOC#) row. Because clear purges all S3
    # objects up front, the last S3 delete must precede the first binary
    # metadata-row delete.
    last_s3 = max(
        idx for idx, entry in enumerate(log) if entry[0] == "s3_delete"
    )
    first_binary_row = min(
        idx
        for idx, entry in enumerate(log)
        if entry[0] == "row_delete"
        and (keys.DOC_PREFIX in entry[1] or keys.PHOTO_PREFIX in entry[1])
    )
    assert last_s3 < first_binary_row


# --- Requirement 8.5: children deleted before the parent property row --------


def test_children_deleted_before_parent_property_row(repo, files, user):
    seeded = _seed_full_property(repo, files, user)
    log: list[tuple[str, str]] = []

    recording_repo = RecordingRepo(repo, log)
    recording_s3 = RecordingS3(files, log)

    result = BackupService(recording_repo, recording_s3, user).clear()
    assert result.is_ok

    property_id = seeded["property_id"]
    pk = keys.property_scoped_pk(property_id)

    row_deletes = [entry[1] for entry in log if entry[0] == "row_delete"]

    # The parent rows: the property's META mirror and its USER#/PROP# list row.
    meta_key = f"{pk}|{keys.META_SK}"
    list_key = (
        f"{keys.user_pk(USER_ID)}|{keys.property_user_sk(property_id)}"
    )
    assert meta_key in row_deletes
    assert list_key in row_deletes

    meta_idx = row_deletes.index(meta_key)
    list_idx = row_deletes.index(list_key)

    # Every child row (same property partition, SK != META) is deleted before
    # both parent rows.
    child_indices = [
        i
        for i, key in enumerate(row_deletes)
        if key.startswith(f"{pk}|") and key != meta_key
    ]
    assert child_indices, "expected the property to have child rows"
    assert max(child_indices) < meta_idx
    assert max(child_indices) < list_idx

    # And there is at least one of each child kind, to prove the ordering holds
    # for real children rather than an empty partition.
    def has_child(marker: str) -> bool:
        return any(
            key.startswith(f"{pk}|") and marker in key.split("|", 1)[1]
            for key in row_deletes
        )

    assert has_child(keys.TXN_PREFIX)  # transactions (and DOC receipt rows)
    assert has_child(keys.DOC_PREFIX)  # receipts
    assert has_child(keys.ASSET_PREFIX)  # assets (and SCHED rows)
    assert has_child(keys.SCHED_PREFIX)  # schedule rows
    assert has_child(keys.PHOTO_PREFIX)  # photo
    assert has_child(keys.USAGE_PREFIX)  # usage year
    assert has_child(keys.DETAILS_SK)  # details
    assert has_child(keys.NOTE_SK)  # note
