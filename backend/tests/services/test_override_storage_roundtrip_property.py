"""Property-based test: overrides survive persistence unchanged.

Feature: depreciation-override-and-whole-dollar-display, Property 8:
overrides survive persistence unchanged.

Writes an asset with a valid override map via the real DepreciationService over
a moto-backed table and reads it back, asserting the map round-trips with int
keys and Decimal values; an asset with no overrides reads back {} and stores no
depreciationOverrides attribute.

Validates: Requirements 1.3, 5.2, 5.3
"""

from __future__ import annotations

from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.models.depreciation import AssetInput
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.depreciation import DepreciationService

TABLE_NAME = "Logstead"
PROP = "prop-1"


@pytest.fixture
def client():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
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
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield ddb


@pytest.fixture
def service(client):
    return DepreciationService(DynamoRepository(client, TABLE_NAME))


def test_override_map_round_trips(service):
    created = service.create_asset(AssetInput(
        property_id=PROP, description="Building",
        cost_basis=Decimal("140000.00"),
        placed_in_service_date="2010-06-01",
        recovery_period_years=Decimal("27.5"),
        depreciation_overrides={2010: Decimal("1952.00")},
    ))
    assert created.is_ok
    asset_id = created.value.id

    fetched = service.get_asset(PROP, asset_id)
    assert fetched.is_ok
    overrides = fetched.value.depreciation_overrides
    assert overrides == {2010: Decimal("1952.00")}
    # Int key, Decimal value.
    (year,) = overrides.keys()
    assert isinstance(year, int)
    assert isinstance(overrides[year], Decimal)


def test_no_override_stores_no_attribute_and_reads_empty(service, client):
    created = service.create_asset(AssetInput(
        property_id=PROP, description="Building",
        cost_basis=Decimal("140000.00"),
        placed_in_service_date="2010-06-01",
        recovery_period_years=Decimal("27.5"),
    ))
    assert created.is_ok
    asset_id = created.value.id

    fetched = service.get_asset(PROP, asset_id)
    assert fetched.is_ok
    assert fetched.value.depreciation_overrides == {}

    # The stored item carries no depreciationOverrides attribute at all.
    raw = client.get_item(
        TableName=TABLE_NAME,
        Key={
            "PK": {"S": keys.property_scoped_pk(PROP)},
            "SK": {"S": keys.asset_sk(asset_id)},
        },
    )
    assert "Item" in raw
    assert "depreciationOverrides" not in raw["Item"]
