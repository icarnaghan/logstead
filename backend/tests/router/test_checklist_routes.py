"""Task 5.2: router tests for the year-end checklist routes (moto-backed)."""
from __future__ import annotations

import json

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import _dispatch, handler
from logstead.services.checklist import ITEM_IDS
from logstead.services.checklist_config import CHECKLIST_CONFIG
from logstead.services.dashboard import latest_tax_year

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-checklist"
REGION = "us-east-1"
USER = "checklist-user-sub"


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


def _make_property(name="House"):
    status, prop = _call("POST", "/properties", body={"name": name, "address_text": "1 St"})
    assert status in (200, 201), prop
    return prop["id"]


def _add_txn(pid, date, amount, type_="income", category="rents-received"):
    status, body = _call(
        "POST",
        f"/properties/{pid}/transactions",
        body={"date": date, "amount": amount, "type": type_, "category_id": category},
    )
    assert status in (200, 201), body


def test_checklist_success_shape(env):
    pid = _make_property()
    _add_txn(pid, "2022-03-01", "1000.00")
    status, body = _call("GET", f"/properties/{pid}/checklist", query={"taxYear": 2022})
    assert status == 200, body
    assert body["property_id"] == pid
    assert body["tax_year"] == 2022
    assert [i["id"] for i in body["items"]] == list(ITEM_IDS)
    counts = body["counts"]
    assert counts["total"] == len(ITEM_IDS)
    assert counts["done"] + counts["needs_attention"] + counts["not_applicable"] == counts["total"]
    by_id = {i["id"]: i for i in body["items"]}
    assert by_id["income_entered"]["status"] == "done"
    assert by_id["expenses_entered"]["status"] == "needs_attention"
    assert body["thresholds"]["large_entry_amount"] == str(CHECKLIST_CONFIG.large_entry_amount)


def test_checklist_year_defaults_when_omitted(env):
    pid = _make_property()
    status, body = _call("GET", f"/properties/{pid}/checklist")
    assert status == 200, body
    assert body["tax_year"] == latest_tax_year()


@pytest.mark.parametrize("bad", ["abc", "1899", "2201"])
@pytest.mark.parametrize("kind", ["property", "portfolio"])
def test_invalid_tax_year_is_400(env, bad, kind):
    pid = _make_property()
    path = f"/properties/{pid}/checklist" if kind == "property" else "/checklist/summary"
    status, body = _call("GET", path, query={"taxYear": bad})
    assert status == 400, body
    assert body["field"] == "taxYear"


@pytest.mark.parametrize("method", ["PUT", "POST", "DELETE"])
@pytest.mark.parametrize(
    "path",
    [
        "/properties/p1/checklist",
        "/properties/p1/checklist/summary",
        "/checklist/summary",
    ],
)
def test_non_get_methods_resolve_to_no_route(env, method, path):
    assert _dispatch(method, path) is None
    status, _ = _call(method, path)
    assert status == 404


def test_property_summary_most_recent_years_descending(env):
    pid = _make_property()
    for year in range(2014, 2023):  # nine Data_Years
        _add_txn(pid, f"{year}-02-01", "100.00")
    status, body = _call("GET", f"/properties/{pid}/checklist/summary")
    assert status == 200, body
    years = [y["tax_year"] for y in body["years"]]
    assert years == [2022, 2021, 2020, 2019, 2018]
    assert len(years) == CHECKLIST_CONFIG.summary_year_count


def test_property_summary_empty_property(env):
    pid = _make_property()
    status, body = _call("GET", f"/properties/{pid}/checklist/summary")
    assert status == 200, body
    assert body["years"] == []


def test_portfolio_summary_user_without_property(env):
    status, body = _call("GET", "/checklist/summary", query={"taxYear": 2022})
    assert status == 200, body
    assert body["tax_year"] == 2022
    assert body["properties"] == []


def test_counts_agree_across_the_three_routes(env):
    pid = _make_property("A")
    other = _make_property("B")
    _add_txn(pid, "2021-03-01", "1200.00")
    _add_txn(pid, "2022-03-01", "2000.00")
    _add_txn(pid, "2022-04-01", "300.00", "expense", "repairs")
    _add_txn(other, "2022-05-01", "50.00", "expense", "supplies")

    _, checklist = _call("GET", f"/properties/{pid}/checklist", query={"taxYear": 2022})
    _, summary = _call("GET", f"/properties/{pid}/checklist/summary")
    _, portfolio = _call("GET", "/checklist/summary", query={"taxYear": 2022})

    year_row = next(y for y in summary["years"] if y["tax_year"] == 2022)
    row = next(p for p in portfolio["properties"] if p["property_id"] == pid)
    assert checklist["counts"] == year_row["counts"] == row["counts"]
    assert {p["property_id"] for p in portfolio["properties"]} == {pid, other}


def test_existing_property_routes_still_resolve(env):
    pid = _make_property()
    for path, expected in [
        ("/properties", "_list_properties"),
        (f"/properties/{pid}", "_get_property"),
        (f"/properties/{pid}/transactions", "_list_transactions"),
        (f"/properties/{pid}/checklist", "_property_checklist"),
        (f"/properties/{pid}/checklist/summary", "_property_checklist_summary"),
        ("/checklist/summary", "_portfolio_checklist_summary"),
    ]:
        found = _dispatch("GET", path)
        assert found is not None, path
        assert found[0].__name__.lstrip("_") .endswith(expected.lstrip("_")), (path, found[0])
    # A property id literally named "checklist" is still captured by the id template.
    found = _dispatch("GET", "/properties/checklist")
    assert found is not None and found[1] == {"propertyId": "checklist"}
