"""Task 5.6: moto-backed example test for ``BackupService.restore`` (Req 2.6).

Covers the empty-document restore edge case: restoring a backup document with no
properties clears the user's existing data and returns an empty
``RestoreSummary``. Seeds a populated property through the real services against
a moto DynamoDB (base table + GSI1 + GSI2) and moto S3 bucket, restores an
empty document, then asserts the user's partitions are empty and the summary is
all-zero.
"""

from __future__ import annotations

from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.backup import RestoreSummary
from logstead.models.depreciation import AssetInput
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
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


def _service(repo, files, user) -> BackupService:
    return BackupService(repo, files, user)


def _seed_populated_property(repo, files, user) -> str:
    """Seed one property with a note, usage, a transaction, and an asset."""
    properties = PropertyService(repo, user)
    transactions = TransactionService(repo, files)
    depreciation = DepreciationService(repo)

    created = properties.create(
        PropertyInput(
            name="Maple Street Duplex",
            address_text="123 Maple St",
            property_type="single_family",
        )
    )
    assert created.is_ok
    prop = created.value

    assert properties.set_note(prop.id, "A note.").is_ok
    assert properties.set_usage_days(prop.id, 2023, 300, 0).is_ok

    assert transactions.create(
        TransactionInput(
            property_id=prop.id,
            date="2024-03-01",
            amount=Decimal("1850.00"),
            type="income",
            category_id="rents-received",
            description=None,
        )
    ).is_ok

    assert depreciation.create_asset(
        AssetInput(
            property_id=prop.id,
            description="HVAC system",
            cost_basis=Decimal("8000.00"),
            placed_in_service_date="2023-06-15",
            recovery_period_years=Decimal("27.5"),
        )
    ).is_ok

    return prop.id


def _user_partition_rows(repo, property_id: str) -> list[dict]:
    """Every row the user owns: the USER# list rows + the property partition."""
    user_rows = repo.query(keys.user_pk(USER_ID))
    property_rows = repo.query(keys.property_scoped_pk(property_id))
    return list(user_rows) + list(property_rows)


def test_empty_document_restore_clears_and_returns_empty_summary(
    repo, files, user
):
    """Req 2.6: an empty-properties document clears data, empty summary back."""
    property_id = _seed_populated_property(repo, files, user)

    # Precondition: the user actually has data before the restore.
    assert _user_partition_rows(repo, property_id), "seed must create rows"

    empty_document = {
        "schema_version": "1",
        "exported_at": "2025-02-14T10:30:00+00:00",
        "properties": [],
    }

    result = _service(repo, files, user).restore(empty_document)

    assert result.is_ok, f"empty restore should succeed: {result.error!r}"
    assert result.value == RestoreSummary(
        properties=0, transactions=0, assets=0, usage_years=0
    )

    # The seeded data is gone: no rows remain in the user's partitions.
    assert _user_partition_rows(repo, property_id) == []
    # The property no longer appears in the owned-property list.
    assert PropertyService(repo, user).list() == []


def test_restore_with_loan_writes_loan_and_recomputed_rollups(
    repo, files, user
):
    """Req 11.3-11.5: a restored loan keeps id/timestamps; rollups recomputed."""
    document = {
        "schema_version": "1",
        "exported_at": "2025-02-14T10:30:00+00:00",
        "properties": [
            {
                "id": "prop-1",
                "name": "Maple",
                "address_text": "123 Maple St",
                "loans": [
                    {
                        "id": "loan-1",
                        "property_id": "prop-1",
                        "description": "Mortgage",
                        "annual_interest_rate": "6.5",
                        "monthly_payment": "1500.00",
                        "anchor_balance": "120000.00",
                        "anchor_date": "2023-02-01",
                        "interest_overrides": {"2021": "4321.00"},
                        "created_at": "2023-01-15T00:00:00+00:00",
                        "updated_at": "2023-01-16T00:00:00+00:00",
                    }
                ],
            }
        ],
    }

    result = _service(repo, files, user).restore(document)

    assert result.is_ok, result.error
    assert result.value.loans == 1

    rows = repo.query(
        keys.property_scoped_pk("prop-1"),
        sk_begins_with=keys.loan_list_prefix(),
        money_attrs=set(),
    )
    loan_rows = [r for r in rows if not keys.is_loan_year_sk(r["SK"])]
    rollup_rows = [r for r in rows if keys.is_loan_year_sk(r["SK"])]
    assert [r["SK"] for r in loan_rows] == [keys.loan_sk("loan-1")]
    assert loan_rows[0]["createdAt"] == "2023-01-15T00:00:00+00:00"
    assert loan_rows[0]["updatedAt"] == "2023-01-16T00:00:00+00:00"
    assert len(rollup_rows) >= 2  # many payments from 2023 span several years
    sks = {r["SK"] for r in rollup_rows}
    assert keys.loan_year_sk("loan-1", 2023) in sks
    # The pre-anchor override year gets an override-only rollup row.
    assert keys.loan_year_sk("loan-1", 2021) in sks


def _loan_document(loan: dict) -> dict:
    return {
        "schema_version": "1",
        "exported_at": "2025-02-14T10:30:00+00:00",
        "properties": [
            {
                "id": "prop-1",
                "name": "Maple",
                "address_text": "123 Maple St",
                "loans": [loan],
            }
        ],
    }


def test_restore_rejects_loan_lacking_anchor_fields_and_persists_nothing(
    repo, files, user
):
    """Req 9.4: an origination-shape loan rejects the whole restore."""
    legacy_loan = {
        "id": "loan-1",
        "property_id": "prop-1",
        "description": "Mortgage",
        "original_principal": "120000.00",
        "annual_interest_rate": "6.5",
        "term_months": 360,
        "first_payment_date": "2023-02-01",
    }

    result = _service(repo, files, user).restore(_loan_document(legacy_loan))

    assert not result.is_ok
    assert repo.query(keys.property_scoped_pk("prop-1")) == []
    assert repo.query(keys.user_pk(USER_ID)) == []


def test_restore_document_without_loans_creates_zero_loans(repo, files, user):
    """Req 9.7: a loan-free document restores with a loan count of 0."""
    document = _loan_document({})
    del document["properties"][0]["loans"]

    result = _service(repo, files, user).restore(document)

    assert result.is_ok, result.error
    assert result.value.properties == 1
    assert result.value.loans == 0
    rows = repo.query(
        keys.property_scoped_pk("prop-1"),
        sk_begins_with=keys.loan_list_prefix(),
        money_attrs=set(),
    )
    assert rows == []
