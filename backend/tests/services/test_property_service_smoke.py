"""Task 6.1 verification: PropertyService CRUD, usage days, and delete guard.

This is a small moto-backed smoke check confirming the service works end to end
against a single-table DynamoDB (create/list/get/update, the deletion guard, and
usage days). The full property-based tests (6.2-6.4) and CRUD happy-path unit
tests (6.5) are separate tasks and are intentionally not implemented here.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.models.property import PropertyInput
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.property import PropertyService

TABLE_NAME = "Logstead"


@pytest.fixture
def client():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
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
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield ddb


@pytest.fixture
def repo(client):
    return DynamoRepository(client, TABLE_NAME)


@pytest.fixture
def service(repo):
    return PropertyService(repo, UserContext(user_id="user-1"))


def test_create_list_get_update(service):
    created = service.create(
        PropertyInput(name="Maple St", address_text="1 Maple St", property_type="sfr")
    )
    assert created.is_ok
    prop = created.value
    assert prop.id and prop.user_id == "user-1"
    assert prop.created_at and prop.updated_at

    listed = service.list()
    assert [p.id for p in listed] == [prop.id]

    got = service.get(prop.id)
    assert got.is_ok and got.value.name == "Maple St"

    updated = service.update(
        prop.id,
        PropertyInput(name="Maple Street", address_text="1 Maple St", property_type="sfr"),
    )
    assert updated.is_ok
    assert updated.value.name == "Maple Street"
    assert updated.value.created_at == prop.created_at
    assert updated.value.updated_at != prop.created_at
    assert service.get(prop.id).value.name == "Maple Street"


def test_create_rejects_blank_fields(service):
    blank_name = service.create(PropertyInput(name="  ", address_text="1 Maple St"))
    assert not blank_name.is_ok
    assert blank_name.error.kind == "validation"
    assert blank_name.error.field == "name"

    blank_addr = service.create(PropertyInput(name="Maple", address_text=""))
    assert not blank_addr.is_ok
    assert blank_addr.error.field == "address_text"


def test_get_scoped_to_owner(repo):
    owner = PropertyService(repo, UserContext(user_id="owner"))
    other = PropertyService(repo, UserContext(user_id="intruder"))
    prop = owner.create(PropertyInput(name="P", address_text="A")).value

    assert owner.get(prop.id).is_ok
    intruder_get = other.get(prop.id)
    assert not intruder_get.is_ok and intruder_get.error.kind == "not_found"
    assert other.list() == []


def test_delete_guarded_by_transactions(repo, service):
    prop = service.create(PropertyInput(name="P", address_text="A")).value

    # No associations -> deletes cleanly.
    empty = service.create(PropertyInput(name="Empty", address_text="B")).value
    assert service.delete(empty.id).is_ok
    assert service.get(empty.id).error.kind == "not_found"

    # Add a transaction under the property; deletion must now be blocked.
    repo.put_item(
        {
            "PK": keys.property_scoped_pk(prop.id),
            "SK": keys.transaction_sk(date(2024, 3, 1), "txn-1"),
            "amount": Decimal("100.00"),
        }
    )
    blocked = service.delete(prop.id)
    assert not blocked.is_ok and blocked.error.kind == "conflict"
    assert service.get(prop.id).is_ok  # still present


def test_delete_guarded_by_assets(repo, service):
    prop = service.create(PropertyInput(name="P", address_text="A")).value
    repo.put_item(
        {
            "PK": keys.property_scoped_pk(prop.id),
            "SK": keys.asset_sk("asset-1"),
            "costBasis": Decimal("5000.00"),
        }
    )
    blocked = service.delete(prop.id)
    assert not blocked.is_ok and blocked.error.kind == "conflict"


def test_usage_days_round_trip(service):
    prop = service.create(PropertyInput(name="P", address_text="A")).value

    stored = service.set_usage_days(prop.id, 2024, fair_rental_days=300, personal_use_days=10)
    assert stored.is_ok

    read = service.get_usage_days(prop.id, 2024)
    assert read.is_ok
    assert read.value.fair_rental_days == 300
    assert read.value.personal_use_days == 10
    assert read.value.tax_year == 2024

    assert service.get_usage_days(prop.id, 2023).error.kind == "not_found"


def test_usage_days_rejects_negative(service):
    prop = service.create(PropertyInput(name="P", address_text="A")).value
    bad = service.set_usage_days(prop.id, 2024, fair_rental_days=-1, personal_use_days=0)
    assert not bad.is_ok and bad.error.kind == "validation"
    assert bad.error.field == "fair_rental_days"
