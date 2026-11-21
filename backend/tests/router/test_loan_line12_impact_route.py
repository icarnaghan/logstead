"""Task 5.3: ``GET /properties/{propertyId}/loans/line-12-impact`` routing and shape.

Runs through the real handler against moto-backed DynamoDB, in the style of
``test_business_routes.py``.
"""

from __future__ import annotations

import json
import re

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import handler

TABLE_NAME = "Logstead"
REGION = "us-east-1"
USER_SUB = "user-line12-1"
OTHER_SUB = "user-line12-2"


def _gsi(name: str) -> dict:
    return {
        "IndexName": name,
        "KeySchema": [
            {"AttributeName": f"{name}PK", "KeyType": "HASH"},
            {"AttributeName": f"{name}SK", "KeyType": "RANGE"},
        ],
        "Projection": {"ProjectionType": "ALL"},
    }


@pytest.fixture
def wired():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        attrs = ["PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK"]
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": a, "AttributeType": "S"} for a in attrs
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[_gsi("GSI1"), _gsi("GSI2")],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket="logstead-files-line12")
        handler_module.configure(
            repo=DynamoRepository(ddb, TABLE_NAME),
            files=S3FileAdapter(s3, "logstead-files-line12"),
        )
        yield
    handler_module.reset_wiring()


def _call(method: str, path: str, *, sub: str = USER_SUB, body=None) -> dict:
    event: dict = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": {"sub": sub}}},
        },
        "rawPath": path,
    }
    if body is not None:
        event["body"] = json.dumps(body)
    return handler(event)


def _setup_property_with_loan_and_manual_interest() -> str:
    resp = _call("POST", "/properties", body={"name": "Maple", "address_text": "1 Maple"})
    assert resp["statusCode"] == 201, resp["body"]
    pid = json.loads(resp["body"])["id"]
    resp = _call(
        "POST",
        f"/properties/{pid}/loans",
        body={
            "description": "Mortgage",
            "annual_interest_rate": "6.5",
            "monthly_payment": "1896.20",
            "anchor_balance": "300000.00",
            "anchor_date": "2023-01-01",
        },
    )
    assert resp["statusCode"] == 201, resp["body"]
    resp = _call(
        "POST",
        f"/properties/{pid}/transactions",
        body={
            "date": "2023-06-15",
            "amount": "1000.5",
            "type": "expense",
            "category_id": "mortgage-interest-banks",
        },
    )
    assert resp["statusCode"] == 201, resp["body"]
    return pid


def test_route_resolves_to_line12_handler_not_get_loan():
    from logstead.router import handler as h

    templates = [(m, p, fn) for m, p, fn, _ in h._ROUTES]
    impact = ("GET", "/properties/{propertyId}/loans/line-12-impact")
    by_key = {(m, p): fn for m, p, fn in templates}
    assert by_key[impact] is h._loan_line12_impact
    order = [(m, p) for m, p, _ in templates]
    assert order.index(impact) < order.index(
        ("GET", "/properties/{propertyId}/loans/{loanId}")
    )


def test_line12_impact_returns_expected_shape(wired):
    pid = _setup_property_with_loan_and_manual_interest()
    resp = _call("GET", f"/properties/{pid}/loans/line-12-impact")
    assert resp["statusCode"] == 200, resp["body"]
    data = json.loads(resp["body"])
    assert len(data) == 1
    row = data[0]
    assert set(row) == {"tax_year", "loan_interest", "superseded_manual_interest"}
    assert row["tax_year"] == 2023
    money = re.compile(r"^\d+\.\d{2}$")
    assert money.match(row["loan_interest"])
    assert row["superseded_manual_interest"] == {"amount": "1000.50", "count": 1}


def test_line12_impact_empty_without_loans(wired):
    resp = _call("POST", "/properties", body={"name": "Oak", "address_text": "2 Oak"})
    pid = json.loads(resp["body"])["id"]
    resp = _call("GET", f"/properties/{pid}/loans/line-12-impact")
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == []


def test_line12_impact_foreign_property_is_404(wired):
    pid = _setup_property_with_loan_and_manual_interest()
    resp = _call("GET", f"/properties/{pid}/loans/line-12-impact", sub=OTHER_SUB)
    assert resp["statusCode"] == 404
