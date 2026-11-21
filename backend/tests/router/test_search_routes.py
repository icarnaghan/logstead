"""Task 7.5: router tests for ``GET /search`` (moto-backed)."""
from __future__ import annotations

import json
import logging
import uuid

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import _dispatch, handler

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-search"
REGION = "us-east-1"
USER = "search-user-a"


@pytest.fixture
def env():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": n, "AttributeType": "S"}
                for n in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": f"GSI{i}",
                    "KeySchema": [
                        {"AttributeName": f"GSI{i}PK", "KeyType": "HASH"},
                        {"AttributeName": f"GSI{i}SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
                for i in (1, 2)
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        handler_module.configure(
            repo=DynamoRepository(ddb, TABLE_NAME), files=S3FileAdapter(s3, BUCKET)
        )
        yield
        handler_module.reset_wiring()


def _call(method, path, *, body=None, query=None, sub=USER):
    event = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": {"sub": sub}}},
        },
        "rawPath": path,
    }
    if body is not None:
        event["body"] = json.dumps(body)
    if query is not None:
        event["queryStringParameters"] = {k: str(v) for k, v in query.items()}
    resp = handler(event)
    return resp["statusCode"], (json.loads(resp["body"]) if resp["body"] else None)


OTHER = "search-user-b"
SECRET_Q = "zebraquartz-secret"


def _make_property(name="House", sub=USER):
    status, prop = _call("POST", "/properties", body={"name": name, "address_text": "1 St"}, sub=sub)
    assert status in (200, 201), prop
    return prop["id"]


def _make_txn(pid, description, amount="1234.50", sub=USER):
    status, txn = _call(
        "POST",
        f"/properties/{pid}/transactions",
        body={"date": "2023-06-01", "amount": amount, "type": "expense",
              "category_id": "repairs", "description": description},
        sub=sub,
    )
    assert status in (200, 201), txn
    return txn


def _raw(method, path, query=None, sub=USER):
    event = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": {"sub": sub}}},
        },
        "rawPath": path,
    }
    if query is not None:
        event["queryStringParameters"] = query
    return handler(event)


def _group(body, kind):
    return next(g for g in body["groups"] if g["kind"] == kind)


def test_success_returns_six_groups_with_stringified_money(env):
    pid = _make_property()
    _make_txn(pid, "Oak fence repair")
    status, body = _call("GET", "/search", query={"q": "oak"})
    assert status == 200, body
    assert [g["kind"] for g in body["groups"]] == [
        "property", "transaction", "itemized_entry", "asset", "loan", "business",
    ]
    hits = _group(body, "transaction")["hits"]
    assert len(hits) == 1
    assert isinstance(hits[0]["amount"], str) and hits[0]["amount"] == "1234.50"
    assert body["truncated"] is False


def test_property_filter_and_user_scoping(env):
    pid = _make_property("Oak House")
    _make_property("Oak Cabin", sub=OTHER)
    status, body = _call("GET", "/search", query={"q": "oak", "propertyId": pid})
    assert status == 200, body
    assert _group(body, "property")["total"] == 0  # property rows skipped when filtered
    status, body = _call("GET", "/search", query={"q": "oak"})
    names = [h["title"] for h in _group(body, "property")["hits"]]
    assert names == ["Oak House"]


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ({}, "q"),
        ({"q": "a"}, "q"),
        ({"q": "x" * 101}, "q"),
        ({"q": "oak", "limit": "abc"}, "limit"),
        ({"q": "oak", "limit": "0"}, "limit"),
        ({"q": "oak", "limit": "26"}, "limit"),
        ({"q": "oak", "limit": "2.5"}, "limit"),
    ],
)
def test_invalid_q_or_limit_is_400(env, query, field):
    status, body = _call("GET", "/search", query=query)
    assert status == 400, body
    assert body["error"] == "validation"
    assert body["field"] == field


def test_bad_missing_and_foreign_property_id_give_identical_404(env):
    foreign = _make_property(sub=OTHER)
    responses = [
        _raw("GET", "/search", {"q": "oak", "propertyId": pid})
        for pid in (foreign, str(uuid.uuid4()), "bad id#!", "x" * 200)
    ]
    assert all(r["statusCode"] == 404 for r in responses), responses
    assert len({(r["statusCode"], r["body"]) for r in responses}) == 1
    assert json.loads(responses[0]["body"])["message"] == "Property not found."
    # Same bytes as the property routes' own not-found.
    prop = _raw("GET", f"/properties/{uuid.uuid4()}")
    assert prop["body"] == responses[0]["body"]


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_only_get_resolves(env, method):
    assert _dispatch(method, "/search") is None
    assert _dispatch("GET", "/search") is not None
    status, body = _call(method, "/search", body={}, query={"q": "oak"})
    assert status == 404, body


def test_requires_authentication(env):
    resp = handler({"requestContext": {"http": {"method": "GET", "path": "/search"}},
                    "rawPath": "/search", "queryStringParameters": {"q": "oak"}})
    assert resp["statusCode"] == 401


def test_query_text_is_never_logged(env, caplog):
    pid = _make_property()
    _make_txn(pid, SECRET_Q)
    with caplog.at_level(logging.DEBUG, logger="logstead"):
        status, body = _call("GET", "/search", query={"q": SECRET_Q})
        _call("GET", "/search", query={"q": SECRET_Q, "limit": "bad"})
        _call("GET", "/search", query={"q": SECRET_Q, "propertyId": str(uuid.uuid4())})
    assert status == 200 and _group(body, "transaction")["total"] == 1
    # Only application loggers: botocore debug output echoes stored items.
    ours = [r for r in caplog.records if r.name.startswith("logstead")]
    assert any("search completed" in r.getMessage() for r in ours)
    assert all(SECRET_Q not in r.getMessage() for r in ours)
