"""Task 5.2: router tests for the itemized-expense routes.

Success and field-identifying validation per route, body extras ignored, the
generic create route cannot set the itemized marker, and existing route matching
still works. Runs against moto-backed DynamoDB and S3.
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
BUCKET = "logstead-files-itemized"
REGION = "us-east-1"
USER = "user-sub"


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


def _call(method, path, *, body=None, query=None):
    event = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": {"sub": USER}}},
        },
        "rawPath": path,
    }
    if body is not None:
        event["body"] = json.dumps(body)
    if query is not None:
        event["queryStringParameters"] = {k: str(v) for k, v in query.items()}
    resp = handler(event)
    return resp["statusCode"], (json.loads(resp["body"]) if resp["body"] else None)


@pytest.fixture
def pid(env):
    status, prop = _call("POST", "/properties",
                         body={"name": "House", "address_text": "1 St"})
    assert status == 201
    return prop["id"]


def _base(pid, cat="repairs"):
    return f"/properties/{pid}/itemized/{cat}"


def _entry(date="2023-05-01", amount="10.00", description="Fix", **extra):
    return {"date": date, "amount": amount, "description": description, **extra}


def _create(pid, **kw):
    status, payload = _call("POST", _base(pid) + "/entries", body=_entry(**kw))
    assert status == 201, payload
    return payload


def _summary(pid, year=2023):
    status, payload = _call("GET", _base(pid), query={"taxYear": year})
    assert status == 200, payload
    return payload


# --- success ----------------------------------------------------------------


def test_entry_and_total_lifecycle(pid):
    created = _create(pid, amount="12.5", notes="  inv 7 ")
    assert created["amount"] == "12.50"
    assert created["itemized"] is True
    assert created["notes"] == "inv 7"
    assert created["type"] == "expense"

    s = _summary(pid)
    assert s["itemized_sum"] == "12.50" and s["line_source"] == "itemized"
    assert s["entered_total"] is None

    status, updated = _call("PUT", f"{_base(pid)}/entries/{created['id']}",
                            body=_entry(amount="20.00", description="Fix 2"))
    assert status == 200 and updated["amount"] == "20.00"
    assert updated["id"] == created["id"] and updated["itemized"] is True

    status, s = _call("PUT", _base(pid) + "/total",
                      body={"tax_year": 2023, "amount": "100.00"})
    assert status == 200
    assert s["entered_total"] == "100.00" and s["line_source"] == "entered_total"
    assert s["remainder"] == "80.00"

    status, s = _call("DELETE", _base(pid) + "/total", query={"taxYear": 2023})
    assert status == 200 and s["entered_total"] is None
    assert s["line_source"] == "itemized"

    status, payload = _call("DELETE", f"{_base(pid)}/entries/{created['id']}")
    assert status == 200
    assert _summary(pid)["line_source"] == "none"


# --- validation names the field ---------------------------------------------


def _field(result):
    status, payload = result
    assert status == 400, (status, payload)
    return payload["field"]


@pytest.mark.parametrize(
    "body,field",
    [
        (_entry(date=""), "date"),
        (_entry(date="not-a-date"), "date"),
        (_entry(amount="0"), "amount"),
        (_entry(amount="-1"), "amount"),
        (_entry(amount="abc"), "amount"),
        (_entry(description=""), "description"),
        (_entry(description="x" * 201), "description"),
        (_entry(notes="n" * 1001), "notes"),
        (_entry(tax_year=2022), "date"),
    ],
)
def test_create_and_update_validation_identifies_field(pid, body, field):
    assert _field(_call("POST", _base(pid) + "/entries", body=body)) == field
    existing = _create(pid)
    assert _field(
        _call("PUT", f"{_base(pid)}/entries/{existing['id']}", body=body)
    ) == field


def test_unsupported_category_is_validation_and_unknown_is_404(pid):
    assert _field(_call("POST", _base(pid, "insurance") + "/entries",
                        body=_entry())) == "category_id"
    status, _ = _call("POST", _base(pid, "nope") + "/entries", body=_entry())
    assert status == 404


def test_summary_and_remove_total_require_valid_tax_year(pid):
    for method in ("GET", "DELETE"):
        path = _base(pid) + ("/total" if method == "DELETE" else "")
        assert _call(method, path)[0] == 400
        assert _call(method, path, query={"taxYear": "abc"})[0] == 400
        assert _call(method, path, query={"taxYear": 1})[0] == 400
        assert _field(_call(method, path, query={"taxYear": "abc"})) == "taxYear"


def test_set_total_validation(pid):
    assert _field(_call("PUT", _base(pid) + "/total",
                        body={"amount": "5.00"})) == "taxYear"
    assert _field(_call("PUT", _base(pid) + "/total",
                        body={"tax_year": 2023, "amount": "0"})) == "amount"
    assert _field(_call("PUT", _base(pid) + "/total",
                        body={"tax_year": 2023, "amount": "x"})) == "amount"


def test_remove_total_when_absent_is_404_on_total(pid):
    status, payload = _call("DELETE", _base(pid) + "/total", query={"taxYear": 2023})
    assert status == 404 and payload["field"] == "total"


def test_missing_entry_is_404(pid):
    for method, body in (("PUT", _entry()), ("DELETE", None)):
        status, _ = _call(method, f"{_base(pid)}/entries/nope-id", body=body)
        assert status == 404


def test_total_on_a_regular_transaction_is_not_an_entry(pid):
    """A non-itemized transaction is not reachable through the entry routes."""
    status, txn = _call("POST", f"/properties/{pid}/transactions", body={
        "date": "2023-05-01", "amount": "40.00", "type": "expense",
        "category_id": "repairs"})
    assert status == 201
    for method, body in (("PUT", _entry()), ("DELETE", None)):
        assert _call(method, f"{_base(pid)}/entries/{txn['id']}", body=body)[0] == 404


# --- body extras ------------------------------------------------------------


def test_body_extras_are_ignored(pid):
    created = _create(pid, itemized=False, imported=True, type="income",
                      property_id="other", user_id="other", category_id="supplies")
    assert created["itemized"] is True
    assert created["imported"] is False
    assert created["type"] == "expense"
    assert created["property_id"] == pid
    assert created["category_id"] == "repairs"

    status, updated = _call(
        "PUT", f"{_base(pid)}/entries/{created['id']}",
        body=_entry(itemized=False, imported=True, type="income",
                    property_id="other", user_id="other"))
    assert status == 200
    assert updated["itemized"] is True and updated["imported"] is False
    assert updated["type"] == "expense" and updated["property_id"] == pid

    status, s = _call("PUT", _base(pid) + "/total", body={
        "tax_year": 2023, "amount": "50.00", "itemized": True, "imported": True,
        "type": "income", "property_id": "other"})
    assert status == 200
    row = s["entered_total_rows"][0]
    assert row["itemized"] is False and row["imported"] is False
    assert row["type"] == "expense" and row["property_id"] == pid
    assert s["itemized_count"] == 1


def test_generic_create_cannot_set_the_marker(pid):
    status, txn = _call("POST", f"/properties/{pid}/transactions", body={
        "date": "2023-05-01", "amount": "40.00", "type": "expense",
        "category_id": "repairs", "itemized": True, "notes": "sneaky",
        "description": "x"})
    assert status == 201, txn
    assert not txn.get("itemized")
    assert not txn.get("notes")
    s = _summary(pid)
    assert s["itemized_count"] == 0 and s["entered_total"] == "40.00"


# --- existing route matching ------------------------------------------------


def test_existing_routes_still_match(pid):
    entry = _create(pid)
    assert _call("GET", f"/properties/{pid}")[0] == 200
    status, listing = _call("GET", f"/properties/{pid}/transactions")
    assert status == 200 and [t["id"] for t in listing] == [entry["id"]]
    assert _call("GET", f"/properties/{pid}/transactions/{entry['id']}")[0] == 200
    assert _call("GET", f"/properties/{pid}/transactions/{entry['id']}/receipts")[0] == 200
    assert _call("GET", f"/properties/{pid}/report", query={"taxYear": 2023})[0] == 200
    assert _call("GET", f"/properties/{pid}/loans")[0] == 200
    assert _call("GET", f"/properties/{pid}/itemized")[0] == 404
