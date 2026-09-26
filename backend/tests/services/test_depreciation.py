"""Verification for depreciable-asset CRUD (task 11.1, Requirement 8).

Moto-backed checks for the asset-CRUD portion of the Depreciation Service:
create (with and without a recovery period -> 27.5 default), cost-basis > 0
and required-field validation, list (excluding schedule rows), get, update,
and delete. The schedule engine (task 11.2), the Property 16-20 property-based
tests (11.3-11.7), and the fuller CRUD happy-path unit suite (11.8) are
intentionally out of scope here.
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
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield ddb


@pytest.fixture
def service(client):
    return DepreciationService(DynamoRepository(client, TABLE_NAME))


def _input(**overrides) -> AssetInput:
    base = dict(
        property_id=PROP,
        description="Roof",
        cost_basis=Decimal("10000.00"),
        placed_in_service_date="2024-03-15",
        recovery_period_years=None,
    )
    base.update(overrides)
    return AssetInput(**base)


# --- create: defaults + persistence -----------------------------------------

def test_create_defaults_recovery_period_to_27_5(service):
    result = service.create_asset(_input(recovery_period_years=None))
    assert result.is_ok
    asset = result.value
    assert asset.recovery_period_years == Decimal("27.5")
    assert asset.id and asset.created_at and asset.updated_at
    assert asset.cost_basis == Decimal("10000.00")


def test_create_respects_explicit_recovery_period(service):
    result = service.create_asset(_input(recovery_period_years=Decimal("5")))
    assert result.is_ok
    assert result.value.recovery_period_years == Decimal("5")


def test_create_persists_cost_basis_as_money_string(service, client):
    asset = service.create_asset(_input()).value
    raw = client.get_item(
        TableName=TABLE_NAME,
        Key={
            "PK": {"S": keys.property_scoped_pk(PROP)},
            "SK": {"S": keys.asset_sk(asset.id)},
        },
    )["Item"]
    # costBasis is a two-decimal string; recovery period is a plain number str.
    assert raw["costBasis"] == {"S": "10000.00"}
    assert raw["recoveryPeriodYears"] == {"S": "27.5"}


# --- create: validation ------------------------------------------------------

@pytest.mark.parametrize("basis", [Decimal("0"), Decimal("-0.01"), Decimal("-100")])
def test_create_rejects_non_positive_cost_basis(service, basis):
    result = service.create_asset(_input(cost_basis=basis))
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "cost_basis"


@pytest.mark.parametrize(
    "field,overrides",
    [
        ("property_id", {"property_id": None}),
        ("property_id", {"property_id": "  "}),
        ("description", {"description": None}),
        ("description", {"description": ""}),
        ("cost_basis", {"cost_basis": None}),
        ("placed_in_service_date", {"placed_in_service_date": None}),
    ],
)
def test_create_rejects_missing_required_field(service, field, overrides):
    result = service.create_asset(_input(**overrides))
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == field


# --- list --------------------------------------------------------------------

def test_list_returns_created_assets(service):
    service.create_asset(_input(description="Roof"))
    service.create_asset(_input(description="HVAC"))
    listed = service.list_assets(PROP)
    assert {a.description for a in listed} == {"Roof", "HVAC"}


def test_list_excludes_schedule_rows(service, client):
    asset = service.create_asset(_input()).value
    # Simulate a materialized schedule row under the asset's SCHED prefix.
    client.put_item(
        TableName=TABLE_NAME,
        Item={
            "PK": {"S": keys.property_scoped_pk(PROP)},
            "SK": {"S": keys.schedule_row_sk(asset.id, 2024)},
            "amount": {"S": "363.64"},
            "remainingBasis": {"S": "9636.36"},
        },
    )
    listed = service.list_assets(PROP)
    assert [a.id for a in listed] == [asset.id]


# --- get ---------------------------------------------------------------------

def test_get_returns_asset(service):
    created = service.create_asset(_input()).value
    fetched = service.get_asset(PROP, created.id)
    assert fetched.is_ok
    assert fetched.value.id == created.id
    assert fetched.value.recovery_period_years == Decimal("27.5")


def test_get_missing_is_not_found(service):
    result = service.get_asset(PROP, "does-not-exist")
    assert not result.is_ok
    assert result.error.kind == "not_found"


# --- update ------------------------------------------------------------------

def test_update_changes_fields_and_revalidates(service):
    created = service.create_asset(_input()).value
    updated = service.update_asset(
        PROP,
        created.id,
        _input(description="New roof", cost_basis=Decimal("12000.00"),
               recovery_period_years=Decimal("39")),
    )
    assert updated.is_ok
    assert updated.value.description == "New roof"
    assert updated.value.cost_basis == Decimal("12000.00")
    assert updated.value.recovery_period_years == Decimal("39")
    assert updated.value.id == created.id
    assert updated.value.created_at == created.created_at


def test_update_rejects_invalid_cost_basis(service):
    created = service.create_asset(_input()).value
    result = service.update_asset(PROP, created.id, _input(cost_basis=Decimal("0")))
    assert not result.is_ok
    assert result.error.field == "cost_basis"


def test_update_missing_is_not_found(service):
    result = service.update_asset(PROP, "nope", _input())
    assert not result.is_ok
    assert result.error.kind == "not_found"


# --- delete ------------------------------------------------------------------

def test_delete_removes_asset(service):
    created = service.create_asset(_input()).value
    assert service.delete_asset(PROP, created.id).is_ok
    assert not service.get_asset(PROP, created.id).is_ok
    assert service.list_assets(PROP) == []


def test_delete_cascades_schedule_rows(service, client):
    asset = service.create_asset(_input()).value
    client.put_item(
        TableName=TABLE_NAME,
        Item={
            "PK": {"S": keys.property_scoped_pk(PROP)},
            "SK": {"S": keys.schedule_row_sk(asset.id, 2024)},
            "amount": {"S": "363.64"},
        },
    )
    assert service.delete_asset(PROP, asset.id).is_ok
    remaining = client.query(
        TableName=TABLE_NAME,
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": {"S": keys.property_scoped_pk(PROP)}},
    )["Items"]
    assert remaining == []


def test_delete_missing_is_not_found(service):
    result = service.delete_asset(PROP, "nope")
    assert not result.is_ok
    assert result.error.kind == "not_found"
