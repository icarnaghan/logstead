"""Happy-path unit tests for asset CRUD + 27.5-year default (task 11.8).

This suite complements the existing verification files without duplicating
them: ``test_depreciation.py`` covers CRUD validation/error paths and
``test_depreciation_schedule.py`` covers the schedule engine and aggregation.
Here we pin down the CRUD *happy paths* end-to-end against a moto-backed table
(with the GSI2 index, since create/update materialize GSI2-keyed schedule
rows): create returns an identified, timestamped asset with the 27.5 default;
list returns assets and excludes schedule rows; get/update/delete behave; and
update re-materializes while delete cascades the schedule.

Requirements: 8.1, 8.4, 8.5, 8.6, 8.7.
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
    """Moto-backed table with the GSI2 index create/update write rows into."""
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


# --- create happy paths (8.1, 8.4) -------------------------------------------

def test_create_returns_asset_with_id_and_timestamps(service):
    """8.1: a created asset is identified and carries create/update stamps."""
    result = service.create_asset(_input())
    assert result.is_ok
    asset = result.value
    assert asset.id
    assert asset.property_id == PROP
    assert asset.description == "Roof"
    assert asset.cost_basis == Decimal("10000.00")
    assert asset.placed_in_service_date == "2024-03-15"
    assert asset.created_at is not None
    assert asset.updated_at is not None
    # On create the two timestamps are set together.
    assert asset.created_at == asset.updated_at


def test_create_defaults_recovery_period_when_unspecified(service):
    """8.4: an unspecified recovery period defaults to 27.5 years."""
    asset = service.create_asset(_input(recovery_period_years=None)).value
    assert asset.recovery_period_years == Decimal("27.5")


def test_create_preserves_explicit_recovery_period(service):
    """8.1/8.4: an explicit recovery period is kept as given, not defaulted."""
    asset = service.create_asset(_input(recovery_period_years=Decimal("5"))).value
    assert asset.recovery_period_years == Decimal("5")


def test_created_asset_is_fetchable_by_id(service):
    """8.1: a created asset round-trips through get with all fields intact."""
    created = service.create_asset(_input()).value
    fetched = service.get_asset(PROP, created.id)
    assert fetched.is_ok
    got = fetched.value
    assert got.id == created.id
    assert got.description == "Roof"
    assert got.cost_basis == Decimal("10000.00")
    assert got.recovery_period_years == Decimal("27.5")
    assert got.placed_in_service_date == "2024-03-15"


# --- list happy paths (8.7) --------------------------------------------------

def test_list_returns_created_assets(service):
    """8.7: listing a property returns the assets created under it."""
    a1 = service.create_asset(_input(description="Roof")).value
    a2 = service.create_asset(_input(description="HVAC")).value
    listed = service.list_assets(PROP)
    assert {a.id for a in listed} == {a1.id, a2.id}
    assert {a.description for a in listed} == {"Roof", "HVAC"}


def test_list_excludes_materialized_schedule_rows(service):
    """8.7: listing returns only asset rows, not the schedule rows create writes.

    Create materializes 29 schedule rows for a 27.5-year asset under the same
    ``ASSET#<id>#SCHED#`` prefix; list must surface exactly one asset item.
    """
    asset = service.create_asset(_input()).value
    # Sanity: the schedule really was materialized under the asset.
    assert service.schedule_for(PROP, asset.id)
    listed = service.list_assets(PROP)
    assert [a.id for a in listed] == [asset.id]


def test_list_returns_multiple_assets_under_one_property(service):
    """8.7: several assets under one property are all listed."""
    ids = {
        service.create_asset(_input(description=f"Asset {i}")).value.id
        for i in range(3)
    }
    listed = service.list_assets(PROP)
    assert {a.id for a in listed} == ids
    assert len(listed) == 3


# --- get happy path ----------------------------------------------------------

def test_get_returns_asset(service):
    """A created asset is retrievable by (property, id)."""
    created = service.create_asset(_input()).value
    fetched = service.get_asset(PROP, created.id)
    assert fetched.is_ok
    assert fetched.value.id == created.id


# --- update happy path (8.5) -------------------------------------------------

def test_update_edits_fields_and_preserves_identity(service):
    """8.5: update saves new values while keeping id, property, and created_at."""
    created = service.create_asset(_input()).value
    updated = service.update_asset(
        PROP,
        created.id,
        _input(
            description="New roof",
            cost_basis=Decimal("12000.00"),
            placed_in_service_date="2024-06-01",
            recovery_period_years=Decimal("39"),
        ),
    )
    assert updated.is_ok
    got = updated.value
    assert got.id == created.id
    assert got.property_id == created.property_id
    assert got.created_at == created.created_at
    assert got.description == "New roof"
    assert got.cost_basis == Decimal("12000.00")
    assert got.placed_in_service_date == "2024-06-01"
    assert got.recovery_period_years == Decimal("39")


def test_update_refreshes_updated_at_and_keeps_created_at(service):
    """8.5: update refreshes updated_at; created_at is untouched.

    The service stamps second-precision UTC times, so an edit within the same
    second could re-use the timestamp; assert updated_at is no earlier than
    created_at rather than strictly greater to keep the test deterministic.
    """
    created = service.create_asset(_input()).value
    updated = service.update_asset(
        PROP, created.id, _input(description="Edited")
    ).value
    assert updated.created_at == created.created_at
    assert updated.updated_at is not None
    assert updated.updated_at >= created.created_at


def test_update_persists_across_get(service):
    """8.5: edited values are durable, not just returned in the result."""
    created = service.create_asset(_input()).value
    service.update_asset(PROP, created.id, _input(description="Persisted"))
    refetched = service.get_asset(PROP, created.id)
    assert refetched.is_ok
    assert refetched.value.description == "Persisted"


def test_update_rematerializes_schedule(service):
    """8.5: editing the recovery period recomputes and replaces the schedule.

    A 27.5-year asset has a 29-row schedule; switching to a 5-year recovery
    period must leave exactly a fresh 6-row schedule (ceil(5) + 1) with no
    stale rows from the prior schedule.
    """
    created = service.create_asset(_input()).value
    assert len(service.schedule_for(PROP, created.id)) == 29

    service.update_asset(
        PROP,
        created.id,
        _input(cost_basis=Decimal("10000.00"), recovery_period_years=Decimal("5")),
    )
    rows = service.schedule_for(PROP, created.id)
    assert len(rows) == 6
    assert sum((r.amount for r in rows), Decimal("0.00")) == Decimal("10000.00")


# --- delete happy paths (8.6) ------------------------------------------------

def test_delete_removes_asset(service):
    """8.6: delete removes the asset so it is no longer gettable or listed."""
    created = service.create_asset(_input()).value
    assert service.delete_asset(PROP, created.id).is_ok
    assert not service.get_asset(PROP, created.id).is_ok
    assert service.list_assets(PROP) == []


def test_delete_cascades_schedule_rows(service, client):
    """8.6: delete removes the asset's materialized schedule rows too.

    After deleting the only asset, the property's partition holds no items at
    all — neither the asset row nor any of its schedule rows remain.
    """
    created = service.create_asset(_input()).value
    assert service.schedule_for(PROP, created.id)  # materialized on create
    assert service.delete_asset(PROP, created.id).is_ok
    assert service.schedule_for(PROP, created.id) == []
    remaining = client.query(
        TableName=TABLE_NAME,
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": {"S": keys.property_scoped_pk(PROP)}},
    )["Items"]
    assert remaining == []


def test_delete_one_asset_leaves_others_intact(service):
    """8.6/8.7: deleting one asset leaves the property's other assets listed."""
    keep = service.create_asset(_input(description="Keep")).value
    drop = service.create_asset(_input(description="Drop")).value
    assert service.delete_asset(PROP, drop.id).is_ok
    listed = service.list_assets(PROP)
    assert [a.id for a in listed] == [keep.id]
    assert service.schedule_for(PROP, keep.id)  # keep's schedule survives
