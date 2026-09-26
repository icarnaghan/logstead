"""Task 3.2: moto-backed example tests for ``BackupService.export`` (Req 1, 13).

Seeds one user with a fully-populated property — details (money + coordinates),
a note, two usage years, an income and an expense transaction, and one
depreciable asset — through the real services against a moto DynamoDB (base
table + GSI1 + GSI2) and a moto S3 bucket, then calls
``BackupService(repo, files, user).export()`` and asserts the produced
``BackupDocument``:

* carries the ``"1"`` schema version and an ``exported_at`` timestamp;
* includes the property, its details, note, usage years, transactions, and
  asset with the exact seeded values (money as exact ``Decimal``);
* renders money as two-decimal strings and coordinates as full-precision
  strings once serialized through the router's ``_to_jsonable`` (Req 13.1, 13.3);
* does NOT embed the category catalog, depreciation schedule rows, or any
  photo/receipt metadata (Req 1.8, 1.9, 1.10).

Export never touches S3, so the S3 adapter is a real moto-backed adapter used
only to construct the collaborators.
"""

from __future__ import annotations

from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.depreciation import AssetInput
from logstead.models.property import (
    PropertyDetails,
    PropertyInput,
    TaxAssessment,
)
from logstead.models.transaction import TransactionInput
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router.handler import _to_jsonable
from logstead.services.backup import BackupService
from logstead.services.depreciation import DepreciationService
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


@pytest.fixture
def seeded(repo, files, user):
    """Seed one property with details, note, usage, transactions, and an asset.

    Returns the ids/values so the assertions can compare against exactly what
    was written.
    """
    properties = PropertyService(repo, user)
    transactions = TransactionService(repo, files)
    depreciation = DepreciationService(repo)

    details = PropertyDetails(
        formatted_address="123 Maple St, Springfield, IL 62704",
        latitude=Decimal("39.781721"),
        longitude=Decimal("-89.650148"),
        year_built=1998,
        last_sale_price=Decimal("245000.00"),
        tax_assessments=[TaxAssessment(year=2023, value=Decimal("230000.00"))],
    )
    created = properties.create(
        PropertyInput(
            name="Maple Street Duplex",
            address_text="123 Maple St, Springfield, IL 62704",
            property_type="single_family",
            details=details,
        )
    )
    assert created.is_ok
    prop = created.value

    note_result = properties.set_note(prop.id, "Tenant lease renews each August.")
    assert note_result.is_ok

    assert properties.set_usage_days(prop.id, 2023, 300, 0).is_ok
    assert properties.set_usage_days(prop.id, 2024, 365, 10).is_ok

    income = transactions.create(
        TransactionInput(
            property_id=prop.id,
            date="2024-03-01",
            amount=Decimal("1850.00"),
            type="income",
            category_id="rents-received",
            description=None,
        )
    )
    assert income.is_ok
    expense = transactions.create(
        TransactionInput(
            property_id=prop.id,
            date="2024-04-15",
            amount=Decimal("312.45"),
            type="expense",
            category_id="repairs",
            description="Fixed the sink",
        )
    )
    assert expense.is_ok

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

    return {
        "property": prop,
        "income": income.value,
        "expense": expense.value,
        "asset": asset.value,
    }


def _service(repo, files, user) -> BackupService:
    return BackupService(repo, files, user)


# --- Document envelope --------------------------------------------------------


def test_export_carries_schema_version_and_exported_at(repo, files, user, seeded):
    doc = _service(repo, files, user).export()

    assert doc.schema_version == "1"
    assert doc.exported_at  # a non-empty ISO timestamp
    assert len(doc.properties) == 1


# --- Property + children present with correct values -------------------------


def test_export_includes_property_fields(repo, files, user, seeded):
    prop = seeded["property"]
    doc = _service(repo, files, user).export()
    exported = doc.properties[0]

    assert exported.id == prop.id
    assert exported.name == "Maple Street Duplex"
    assert exported.address_text == "123 Maple St, Springfield, IL 62704"
    assert exported.property_type == "single_family"
    assert exported.created_at == prop.created_at
    assert exported.updated_at == prop.updated_at


def test_export_includes_details_note_and_usage(repo, files, user, seeded):
    doc = _service(repo, files, user).export()
    exported = doc.properties[0]

    # Details is the sparse details_to_dict output (money/coords as strings).
    assert isinstance(exported.details, dict)
    assert exported.details["formatted_address"] == (
        "123 Maple St, Springfield, IL 62704"
    )
    assert exported.details["latitude"] == "39.781721"
    assert exported.details["longitude"] == "-89.650148"
    assert exported.details["last_sale_price"] == "245000.00"
    assert exported.details["tax_assessments"] == [
        {"year": 2023, "value": "230000.00"}
    ]

    assert exported.note == "Tenant lease renews each August."

    usage_by_year = {u.tax_year: u for u in exported.usage}
    assert usage_by_year[2023].fair_rental_days == 300
    assert usage_by_year[2023].personal_use_days == 0
    assert usage_by_year[2024].fair_rental_days == 365
    assert usage_by_year[2024].personal_use_days == 10


def test_export_includes_transactions_with_exact_money(repo, files, user, seeded):
    doc = _service(repo, files, user).export()
    exported = doc.properties[0]

    by_id = {t.id: t for t in exported.transactions}
    income = by_id[seeded["income"].id]
    expense = by_id[seeded["expense"].id]

    # Money is exact Decimal on the dataclass.
    assert income.amount == Decimal("1850.00")
    assert income.type == "income"
    assert income.category_id == "rents-received"
    assert income.property_id == exported.id

    assert expense.amount == Decimal("312.45")
    assert expense.type == "expense"
    assert expense.category_id == "repairs"
    assert expense.description == "Fixed the sink"


def test_export_includes_asset_with_exact_money(repo, files, user, seeded):
    doc = _service(repo, files, user).export()
    exported = doc.properties[0]

    assert len(exported.assets) == 1
    asset = exported.assets[0]
    assert asset.id == seeded["asset"].id
    assert asset.description == "HVAC system"
    assert asset.cost_basis == Decimal("8000.00")
    assert asset.placed_in_service_date == "2023-06-15"
    assert asset.recovery_period_years == Decimal("27.5")
    assert asset.property_id == exported.id


# --- Money-as-string once serialized through the router ----------------------


def test_serialized_money_and_coordinates_are_strings(repo, files, user, seeded):
    doc = _service(repo, files, user).export()
    body = _to_jsonable(doc)
    exported = body["properties"][0]

    # Transaction / asset money render as two-decimal strings.
    amounts = {t["id"]: t["amount"] for t in exported["transactions"]}
    assert amounts[seeded["income"].id] == "1850.00"
    assert amounts[seeded["expense"].id] == "312.45"
    assert exported["assets"][0]["cost_basis"] == "8000.00"

    # Details money as two-decimal strings, coordinates full-precision strings.
    assert exported["details"]["last_sale_price"] == "245000.00"
    assert exported["details"]["latitude"] == "39.781721"
    assert exported["details"]["longitude"] == "-89.650148"

    # No Decimal or float leaked into the serialized document.
    for value in amounts.values():
        assert isinstance(value, str)
    assert isinstance(exported["assets"][0]["cost_basis"], str)


# --- Exclusions: catalog, schedule rows, photo/receipt metadata --------------


def test_export_excludes_catalog_schedule_and_binary_metadata(
    repo, files, user, seeded
):
    doc = _service(repo, files, user).export()
    body = _to_jsonable(doc)
    exported = body["properties"][0]

    # The category catalog is never embedded — only slug references remain.
    assert "categories" not in body
    assert "category_catalog" not in body
    for txn in exported["transactions"]:
        assert txn["category_id"] in ("rents-received", "repairs")

    # Schedule rows are recomputed on restore, never carried in the document.
    assert "schedule" not in exported
    for asset in exported["assets"]:
        assert "schedule" not in asset
        assert "schedule_rows" not in asset

    # No photo/receipt metadata anywhere in the document.
    property_keys = set(exported.keys())
    assert "photos" not in property_keys
    assert "receipts" not in property_keys
    assert "documents" not in property_keys
    for txn in exported["transactions"]:
        assert "receipts" not in txn
        assert "documents" not in txn


def test_schedule_rows_exist_in_store_but_not_in_document(
    repo, files, user, seeded
):
    """The asset DID materialize schedule rows; export must still omit them."""
    asset = seeded["asset"]
    sched_rows = repo.query(
        keys.property_scoped_pk(asset.property_id),
        sk_begins_with=keys.schedule_list_prefix(asset.id),
        money_attrs={"amount", "remainingBasis"},
    )
    assert sched_rows  # precondition: schedule rows really are stored

    doc = _service(repo, files, user).export()
    exported_asset = doc.properties[0].assets[0]
    # BackupAsset has no schedule field at all.
    assert not hasattr(exported_asset, "schedule")
    assert not hasattr(exported_asset, "schedule_rows")


# --- Empty export -------------------------------------------------------------


def test_export_with_no_properties_is_empty(repo, files, user):
    doc = _service(repo, files, user).export()
    assert doc.schema_version == "1"
    assert doc.exported_at
    assert doc.properties == []
