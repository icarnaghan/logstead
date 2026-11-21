"""Task 2.5: GET /properties/{propertyId}/earliest-year route tests.

Feature: carryforward-tolerance-and-year-range, Property 10: earliest data
year is the minimum activity year.

moto-backed (DynamoDB base + GSI1 + GSI2, S3), wired through
``handler_module.configure(...)`` and seeded via the public POST endpoints.

**Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6, 7.9**
"""

from __future__ import annotations

import json

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import handler

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-earliest-year"
REGION = "us-east-1"

USER_A = "user-earliest-A"
USER_B = "user-earliest-B"


@pytest.fixture
def aws():
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


@pytest.fixture(autouse=True)
def _reset_wiring_after():
    yield
    handler_module.reset_wiring()


@pytest.fixture
def wired(aws):
    ddb, s3 = aws
    handler_module.configure(
        repo=DynamoRepository(ddb, TABLE_NAME), files=S3FileAdapter(s3, BUCKET)
    )


def _event(method: str, path: str, *, sub: str | None, body: dict | None = None):
    event: dict = {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
    }
    if sub is not None:
        event["requestContext"]["authorizer"] = {
            "jwt": {"claims": {"sub": sub, "cognito:username": f"{sub}@example.com"}}
        }
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _create_property(sub: str) -> str:
    resp = handler(
        _event(
            "POST",
            "/properties",
            sub=sub,
            body={"name": "Maple Duplex", "address_text": "100 Maple St"},
        )
    )
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])["id"]


def _create_transaction(sub: str, property_id: str, date: str) -> None:
    resp = handler(
        _event(
            "POST",
            f"/properties/{property_id}/transactions",
            sub=sub,
            body={
                "date": date,
                "amount": "100.00",
                "type": "income",
                "category_id": "rents-received",
            },
        )
    )
    assert resp["statusCode"] == 201, resp["body"]


def _create_asset(sub: str, property_id: str, placed_in_service_date: str) -> None:
    resp = handler(
        _event(
            "POST",
            f"/properties/{property_id}/assets",
            sub=sub,
            body={
                "description": "HVAC system",
                "cost_basis": "27500.00",
                "placed_in_service_date": placed_in_service_date,
            },
        )
    )
    assert resp["statusCode"] == 201, resp["body"]


def _earliest(sub: str | None, property_id: str):
    return handler(
        _event("GET", f"/properties/{property_id}/earliest-year", sub=sub)
    )


def _earliest_year(sub: str, property_id: str):
    resp = _earliest(sub, property_id)
    assert resp["statusCode"] == 200, resp["body"]
    return json.loads(resp["body"])["earliest_year"]


def test_transactions_only_returns_earliest_transaction_year(wired):
    prop = _create_property(USER_A)
    for year in range(2010, 2019):
        _create_transaction(USER_A, prop, f"{year}-06-15")
    assert _earliest_year(USER_A, prop) == 2010


def test_assets_only_returns_earliest_in_service_year(wired):
    prop = _create_property(USER_A)
    _create_asset(USER_A, prop, "2015-03-01")
    _create_asset(USER_A, prop, "2012-11-20")
    assert _earliest_year(USER_A, prop) == 2012


def test_both_smaller_year_wins_when_transaction_is_earlier(wired):
    prop = _create_property(USER_A)
    _create_transaction(USER_A, prop, "2011-05-05")
    _create_asset(USER_A, prop, "2016-01-10")
    assert _earliest_year(USER_A, prop) == 2011


def test_both_smaller_year_wins_when_asset_is_earlier(wired):
    prop = _create_property(USER_A)
    _create_transaction(USER_A, prop, "2019-05-05")
    _create_asset(USER_A, prop, "2014-01-10")
    assert _earliest_year(USER_A, prop) == 2014


def test_neither_returns_null(wired):
    prop = _create_property(USER_A)
    assert _earliest_year(USER_A, prop) is None


def test_other_users_property_is_404(wired):
    prop = _create_property(USER_A)
    _create_transaction(USER_A, prop, "2010-01-01")
    resp = _earliest(USER_B, prop)
    assert resp["statusCode"] == 404, resp["body"]


def test_unauthenticated_is_401(wired):
    prop = _create_property(USER_A)
    assert _earliest(None, prop)["statusCode"] == 401
