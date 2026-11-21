"""Task 3.3: ``GET /dashboard/trends`` route — concrete example integration tests.

Example-based (not property-based) integration tests for the trends endpoint,
mirroring ``test_dashboard_assets_route.py``: a ``moto``-backed single-table
DynamoDB (base + GSI1 + GSI2) plus an S3 bucket are wired via
``handler_module.configure(...)``, portfolios are seeded through the public
``POST`` endpoints, and the serialized ``GET /dashboard/trends`` body is parsed
back from JSON.

Covers:

* **Shape / ordering (Req 2.6, 6.3, 6.5):** a user with a couple of properties
  and transactions + depreciation across 2+ years → 200 with a correctly-shaped
  ``TrendsSeries`` — ascending ``tax_year``s, a per-property point for *every*
  property in *every* year, portfolio totals equal to the exact sum of the
  per-property points, and ``depreciation_total`` present on each year.
* **Empty series (Req 11.4):** a user with no properties → ``years == []``.
* **No taxYear param:** the route neither requires nor consumes a ``taxYear``
  query parameter — passing one does not change the (multi-year) result.
* **Auth (consistent with the other dashboard routes):** an unauthenticated
  request returns the same ``401 unauthorized`` the other dashboard routes do.

Everything runs against in-memory AWS; wiring is reset between tests.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import handler

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-dashboard-trends"
REGION = "us-east-1"

USER_A = "user-dash-trends-A"
USER_B = "user-dash-trends-B"

#: Two-decimal money string, e.g. "0.00", "1250.00", "-3.50" (Req 7.1).
_MONEY_RE = re.compile(r"^-?\d+\.\d{2}$")


# --- moto fixtures -----------------------------------------------------------


@pytest.fixture
def aws():
    """A moto context with the DynamoDB table (GSI1/GSI2) and the S3 bucket."""
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
def s3_files(aws):
    _, s3 = aws
    return S3FileAdapter(s3, BUCKET)


@pytest.fixture(autouse=True)
def _reset_wiring_after():
    """Clear wiring after every test, even those that reconfigure it."""
    yield
    handler_module.reset_wiring()


@pytest.fixture
def wired(repo, s3_files):
    """Inject fully-configured moto-backed wiring (repo + S3 files).

    The shared ``_dashboard_service_or_503`` constructor composes the reporting
    service (which wires a transaction service needing the S3 adapter), so a
    configured bucket is required for the dashboard service to build — exactly
    as in production.
    """
    handler_module.configure(repo=repo, files=s3_files)
    return repo


# --- event / request helpers -------------------------------------------------


def _claims(sub: str) -> dict:
    """Build the verified JWT claim map for a user (as the authorizer delivers)."""
    return {"sub": sub, "cognito:username": f"{sub}@example.com"}


def _event(method: str, path: str, *, sub: str | None = None, query: dict | None = None):
    """Build an API Gateway HTTP API v2 proxy event with an optional identity."""
    event: dict = {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
    }
    if sub is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": _claims(sub)}}
    if query is not None:
        event["queryStringParameters"] = {k: str(v) for k, v in query.items()}
    return event


def _create_property(sub: str, name: str, address: str) -> str:
    resp = handler(
        _event("POST", "/properties", sub=sub)
        | {"body": json.dumps({"name": name, "address_text": address})}
    )
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])["id"]


def _create_transaction(sub: str, property_id: str, body: dict) -> None:
    resp = handler(
        _event("POST", f"/properties/{property_id}/transactions", sub=sub)
        | {"body": json.dumps(body)}
    )
    assert resp["statusCode"] == 201, resp["body"]


def _create_asset(sub: str, property_id: str, **overrides) -> None:
    body = {
        "description": "HVAC system",
        "cost_basis": "27500.00",
        "placed_in_service_date": "2020-01-10",
    }
    body.update(overrides)
    resp = handler(
        _event("POST", f"/properties/{property_id}/assets", sub=sub)
        | {"body": json.dumps(body)}
    )
    assert resp["statusCode"] == 201, resp["body"]


def _get_trends(sub: str, *, query: dict | None = None) -> dict:
    """GET /dashboard/trends; assert 200 and parse the serialized JSON body."""
    resp = handler(_event("GET", "/dashboard/trends", sub=sub, query=query))
    assert resp["statusCode"] == 200, resp["body"]
    return json.loads(resp["body"])


def _income(date: str, amount: str) -> dict:
    return {"date": date, "amount": amount, "type": "income", "category_id": "rents-received"}


def _expense(date: str, amount: str) -> dict:
    return {"date": date, "amount": amount, "type": "expense", "category_id": "repairs"}


# ============================================================================
# Shape / ordering / reconciliation (Req 2.6, 6.3, 6.5)
# ============================================================================


def test_trends_returns_well_shaped_ascending_series_across_multiple_years(wired):
    """A user with 2 properties + data across 2+ years → a correct TrendsSeries.

    Asserts ascending years, a per-property point for every property in every
    year, portfolio totals equal to the exact sum of the per-property points,
    and ``depreciation_total`` present on each year (Req 2.6, 6.3, 6.5).
    """
    prop1 = _create_property(USER_A, "Maple Duplex", "100 Maple St")
    prop2 = _create_property(USER_A, "Oak Cottage", "200 Oak St")

    # Property 1 has income + expenses in 2021 and 2023; a depreciable asset
    # placed in service 2021 contributes Line 18 depreciation from 2021 onward.
    _create_asset(USER_A, prop1, placed_in_service_date="2021-01-10")
    _create_transaction(USER_A, prop1, _income("2021-03-01", "20000.00"))
    _create_transaction(USER_A, prop1, _expense("2021-06-15", "5000.00"))
    _create_transaction(USER_A, prop1, _income("2023-02-01", "22000.00"))
    _create_transaction(USER_A, prop1, _expense("2023-07-20", "6000.00"))

    # Property 2 has income only in 2023 (no 2021 data → a 0.00 point in 2021).
    _create_transaction(USER_A, prop2, _income("2023-05-01", "12000.00"))

    body = _get_trends(USER_A)

    years = body["years"]
    assert isinstance(years, list)

    tax_years = [y["tax_year"] for y in years]
    # Data_Years span every year with Schedule E data (transactions OR
    # depreciation schedule rows), so the asset placed in service 2021 makes
    # 2021..2023 all Data_Years. The series is ascending with no duplicates.
    assert tax_years == sorted(tax_years), "years must be ascending"
    assert len(set(tax_years)) == len(tax_years), "no duplicate years"
    assert 2021 in tax_years and 2023 in tax_years
    # No year *before* the earliest Schedule E data (2021) appears.
    assert min(tax_years) == 2021

    prop_ids = {prop1, prop2}
    for year_entry in years:
        # Every owned property appears as a point in every year.
        points = year_entry["properties"]
        assert {p["property_id"] for p in points} == prop_ids

        # tax_year is the ONLY integer; every money field is a two-decimal string.
        assert isinstance(year_entry["tax_year"], int)
        for field in ("total_income", "total_expenses", "net", "depreciation_total"):
            value = year_entry[field]
            assert isinstance(value, str), f"{field} is not a string: {value!r}"
            assert _MONEY_RE.match(value), f"{field} not two-decimal: {value!r}"
        for point in points:
            for field in ("total_income", "total_expenses", "net"):
                value = point[field]
                assert isinstance(value, str)
                assert _MONEY_RE.match(value), f"point.{field} not two-decimal: {value!r}"

        # Portfolio totals equal the exact-cent sum of the per-property points.
        assert Decimal(year_entry["total_income"]) == sum(
            (Decimal(p["total_income"]) for p in points), Decimal("0.00")
        )
        assert Decimal(year_entry["total_expenses"]) == sum(
            (Decimal(p["total_expenses"]) for p in points), Decimal("0.00")
        )
        assert Decimal(year_entry["net"]) == sum(
            (Decimal(p["net"]) for p in points), Decimal("0.00")
        )

    # 2021: property 2 contributes a 0.00 point; property 1 carries the income.
    year_2021 = next(y for y in years if y["tax_year"] == 2021)
    points_2021 = {p["property_id"]: p for p in year_2021["properties"]}
    assert points_2021[prop2]["total_income"] == "0.00"
    assert points_2021[prop2]["net"] == "0.00"
    assert Decimal(points_2021[prop1]["total_income"]) == Decimal("20000.00")

    # depreciation_total is present and positive in a year with an in-service asset.
    assert Decimal(year_2021["depreciation_total"]) > 0


def test_trends_preserves_non_contiguous_data_years(wired):
    """Gap years with no Schedule E data are omitted, not filled (Req 2.4).

    Uses a transaction-only property (no depreciable asset, so no schedule rows
    bridge the gap): data exists in 2021 and 2023 only, so 2022 is absent.
    """
    prop = _create_property(USER_A, "Maple Duplex", "100 Maple St")
    _create_transaction(USER_A, prop, _income("2021-03-01", "20000.00"))
    _create_transaction(USER_A, prop, _income("2023-02-01", "22000.00"))

    body = _get_trends(USER_A)
    tax_years = [y["tax_year"] for y in body["years"]]
    assert tax_years == [2021, 2023], "the 2022 gap year must be omitted, not filled"


# ============================================================================
# Empty series (Req 11.4)
# ============================================================================


def test_trends_empty_portfolio_returns_empty_years(wired):
    """A user with no properties → 200 with years: [] (Req 11.4)."""
    body = _get_trends(USER_A)
    assert body["years"] == []


# ============================================================================
# No taxYear param required or consumed
# ============================================================================


def test_trends_ignores_taxyear_query_param(wired):
    """The route neither requires nor consumes taxYear — the result is identical."""
    prop = _create_property(USER_A, "Maple Duplex", "100 Maple St")
    _create_transaction(USER_A, prop, _income("2021-03-01", "20000.00"))
    _create_transaction(USER_A, prop, _income("2023-02-01", "22000.00"))

    without_param = _get_trends(USER_A)
    with_param = _get_trends(USER_A, query={"taxYear": 2021})

    # A taxYear value does not narrow or otherwise change the multi-year series.
    assert with_param == without_param
    assert [y["tax_year"] for y in with_param["years"]] == [2021, 2023]

    # Even a non-integer taxYear is harmless because the param is never parsed.
    resp = handler(
        _event("GET", "/dashboard/trends", sub=USER_A, query={"taxYear": "nope"})
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == without_param


# ============================================================================
# Auth (consistent with the other protected dashboard routes)
# ============================================================================


def test_trends_requires_auth(wired):
    """GET /dashboard/trends is protected: no JWT claims → 401 unauthorized."""
    resp = handler(_event("GET", "/dashboard/trends"))  # no sub
    assert resp["statusCode"] == 401
    assert json.loads(resp["body"])["error"] == "unauthorized"
