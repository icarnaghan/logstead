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
