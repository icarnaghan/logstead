"""Task 1.3: ``GET /dashboard/assets`` route handler + integration tests (moto).

Drives the router as an integration boundary (mirroring
``test_backup_routes.py`` and ``test_handler_integration.py``): a ``moto``-backed
DynamoDB table (base + GSI1 + GSI2) is wired via
``handler_module.configure(...)``, and requests are built as API Gateway HTTP
API v2 proxy events with the verified Cognito identity placed at
``event["requestContext"]["authorizer"]["jwt"]["claims"]`` — exactly how the JWT
authorizer delivers it.

Covers the read-only per-property depreciable-assets summary endpoint
(``DashboardService.asset_summary`` behind ``GET /dashboard/assets?taxYear=Y``):

* **Routing / shape (Req 3.1):** a seeded user with properties + assets → 200
  with one entry per property carrying the expected ``asset_count`` and
  ``depreciation_total``.
* **GET-only / no write path (Req 3.2):** the route is registered as ``GET``
  only; there is no ``POST``/``PUT``/``DELETE`` ``/dashboard/assets`` route.
* **taxYear param:** an explicit ``?taxYear=YYYY`` is echoed back as ``tax_year``
  and selects that year's depreciation; omitting it defaults to the latest
  completed tax year (the prior calendar year).
* **User-scoping (Req 3.4):** two users with disjoint properties — A's response
  contains only A's properties, never B's.
* **Money-as-two-decimal-string (Req 3.5):** every ``depreciation_total`` in the
  serialized JSON body is a string matching ``^-?\\d+\\.\\d{2}$`` (through the
  router's ``_to_jsonable``).
* **Empty states (Req 5.1, 5.2):** an empty portfolio returns ``properties: []``;
  an asset-free property returns ``asset_count: 0`` and ``"0.00"``.
* **401 without auth:** the route is protected like every other dashboard route.

Everything runs against in-memory AWS; wiring is reset between tests.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import handler

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-dashboard-assets"
REGION = "us-east-1"

USER_A = "user-dash-assets-A"
USER_B = "user-dash-assets-B"

#: Two-decimal money string, e.g. "0.00", "1250.00", "-3.50" (Req 3.5).
_MONEY_RE = re.compile(r"^-?\d+\.\d{2}$")


# --- moto fixtures -----------------------------------------------------------


@pytest.fixture
def aws():
    """A moto context with the DynamoDB table (GSI1/GSI2) created."""
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

    The ``/dashboard/assets`` handler itself reads only the repo, but the shared
    ``_dashboard_service_or_503`` constructor composes the reporting service
    (which wires a transaction service needing the S3 adapter), so a configured
    bucket is required for the dashboard service to build — exactly as in
    production.
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


def _create_property(sub: str, name: str, address: str) -> dict:
    resp = handler(
        _event("POST", "/properties", sub=sub)
        | {"body": json.dumps({"name": name, "address_text": address})}
    )
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])


def _create_asset(sub: str, property_id: str, **overrides) -> dict:
    body = {
        "description": "HVAC system",
        "cost_basis": "27500.00",
        "placed_in_service_date": "2022-01-10",
    }
    body.update(overrides)
    resp = handler(
        _event("POST", f"/properties/{property_id}/assets", sub=sub)
        | {"body": json.dumps(body)}
    )
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])


def _get_asset_summary(sub: str, *, tax_year: int | None = None) -> dict:
    """GET /dashboard/assets (optionally for a tax year); assert 200 and parse body."""
    query = {"taxYear": tax_year} if tax_year is not None else None
    resp = handler(_event("GET", "/dashboard/assets", sub=sub, query=query))
    assert resp["statusCode"] == 200, resp["body"]
    return json.loads(resp["body"])


def _authoritative_total(repo: DynamoRepository, property_id: str, tax_year: int) -> str:
    """The authoritative per-(property, year) depreciation total as a money string.

    Reads it straight from :class:`DepreciationService` — the same method that
    feeds Schedule E Line 18 — so the endpoint can be asserted against the one
    authoritative source rather than a re-implemented depreciation calculation.
    """
    from logstead.services.depreciation import DepreciationService

    total = DepreciationService(repo).property_depreciation_for_year(
        property_id, tax_year
    )
    return str(total)


# ============================================================================
# Routing / shape (Req 3.1) + taxYear param
# ============================================================================


def test_asset_summary_returns_one_entry_per_property_with_count_and_total(wired, repo):
    """A seeded user with properties + assets → one row per property (Req 3.1)."""
    tax_year = 2023
    prop1 = _create_property(USER_A, "Maple Duplex", "100 Maple St")
    prop2 = _create_property(USER_A, "Oak Cottage", "200 Oak St")
    # prop1 gets two assets; prop2 gets one.
    _create_asset(USER_A, prop1["id"])
    _create_asset(USER_A, prop1["id"], description="Fridge", cost_basis="1800.00")
    _create_asset(USER_A, prop2["id"], description="Roof", cost_basis="12000.00")

    body = _get_asset_summary(USER_A, tax_year=tax_year)

    assert body["tax_year"] == tax_year
    rows = {r["property_id"]: r for r in body["properties"]}
    assert set(rows) == {prop1["id"], prop2["id"]}

    assert rows[prop1["id"]]["property_name"] == "Maple Duplex"
    assert rows[prop1["id"]]["asset_count"] == 2
    assert rows[prop2["id"]]["asset_count"] == 1

    # Each depreciation_total equals the authoritative Line 18 figure (Req 6.1
    # by construction) and is a positive amount for a seeded, in-service asset.
    for pid in (prop1["id"], prop2["id"]):
        expected = _authoritative_total(repo, pid, tax_year)
        assert rows[pid]["depreciation_total"] == expected
        assert float(rows[pid]["depreciation_total"]) > 0.0


def test_asset_summary_taxyear_param_selects_year_and_is_echoed(wired, repo):
    """An explicit ?taxYear=YYYY is echoed as tax_year and drives the totals."""
    prop = _create_property(USER_A, "Maple Duplex", "100 Maple St")
    _create_asset(USER_A, prop["id"])  # placed in service 2022

    body_2022 = _get_asset_summary(USER_A, tax_year=2022)
    body_2023 = _get_asset_summary(USER_A, tax_year=2023)

    assert body_2022["tax_year"] == 2022
    assert body_2023["tax_year"] == 2023

    total_2022 = body_2022["properties"][0]["depreciation_total"]
    total_2023 = body_2023["properties"][0]["depreciation_total"]
    assert total_2022 == _authoritative_total(repo, prop["id"], 2022)
    assert total_2023 == _authoritative_total(repo, prop["id"], 2023)


def test_asset_summary_defaults_to_latest_completed_year_when_taxyear_omitted(wired):
    """Omitting taxYear defaults the returned tax_year to the latest completed year.

    The current calendar year can't be filed yet, so the dashboard default is
    the prior calendar year.
    """
    _create_property(USER_A, "Maple Duplex", "100 Maple St")

    body = _get_asset_summary(USER_A)  # no taxYear query param

    latest_completed_year = datetime.now(timezone.utc).year - 1
    assert body["tax_year"] == latest_completed_year


def test_asset_summary_bad_taxyear_returns_400(wired):
    """A non-integer taxYear surfaces a clean 400 (router _int_param)."""
    _create_property(USER_A, "Maple Duplex", "100 Maple St")
    resp = handler(
        _event("GET", "/dashboard/assets", sub=USER_A, query={"taxYear": "nope"})
    )
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "validation"


# ============================================================================
# GET-only / no write path (Req 3.2)
# ============================================================================


def test_asset_summary_route_registered_get_only(wired):
    """/dashboard/assets is registered as GET only — no write path (Req 3.2)."""
    routes = handler_module._ROUTES
    assets_routes = [
        (method, path) for (method, path, _handler, _public) in routes
        if path == "/dashboard/assets"
    ]
    assert assets_routes == [("GET", "/dashboard/assets")]
    # And it is a public=False (protected) route, consistent with other routes.
    publics = [
        public for (_m, path, _h, public) in routes if path == "/dashboard/assets"
    ]
    assert publics == [False]


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_asset_summary_rejects_write_methods(wired, method):
    """No write verb matches /dashboard/assets → 404 (no write path, Req 3.2)."""
    resp = handler(_event(method, "/dashboard/assets", sub=USER_A))
    assert resp["statusCode"] == 404


# ============================================================================
# User-scoping (Req 3.4)
# ============================================================================


def test_asset_summary_scoped_to_authenticated_user(wired):
    """A seeded as A sees only A's properties, never B's (Req 3.4)."""
    a_prop = _create_property(USER_A, "A Property", "100 A St")
    _create_asset(USER_A, a_prop["id"])
    b_prop = _create_property(USER_B, "B Property", "200 B St")
    _create_asset(USER_B, b_prop["id"])

    a_body = _get_asset_summary(USER_A, tax_year=2023)
    a_ids = {r["property_id"] for r in a_body["properties"]}
    assert a_ids == {a_prop["id"]}
    assert b_prop["id"] not in a_ids

    b_body = _get_asset_summary(USER_B, tax_year=2023)
    b_ids = {r["property_id"] for r in b_body["properties"]}
    assert b_ids == {b_prop["id"]}
    assert a_prop["id"] not in b_ids


# ============================================================================
# Money-as-two-decimal-string (Req 3.5)
# ============================================================================


def test_asset_summary_depreciation_total_is_two_decimal_string(wired):
    """Every depreciation_total serializes as a two-decimal string (Req 3.5)."""
    prop1 = _create_property(USER_A, "Maple Duplex", "100 Maple St")
    prop2 = _create_property(USER_A, "Oak Cottage", "200 Oak St")
    _create_asset(USER_A, prop1["id"])
    # prop2 intentionally has no assets → "0.00".

    body = _get_asset_summary(USER_A, tax_year=2023)
    totals = [r["depreciation_total"] for r in body["properties"]]
    assert len(totals) == 2
    for total in totals:
        assert isinstance(total, str)
        assert _MONEY_RE.match(total), f"not a two-decimal money string: {total!r}"


# ============================================================================
# Empty states (Req 5.1, 5.2)
# ============================================================================


def test_asset_summary_empty_portfolio_returns_empty_properties(wired):
    """A user with no properties → 200 with properties: [] (Req 5.1)."""
    body = _get_asset_summary(USER_A, tax_year=2023)
    assert body["properties"] == []


def test_asset_summary_asset_free_property_is_zero_count_and_zero_total(wired):
    """A property with no assets → asset_count 0 and "0.00" (Req 5.2)."""
    prop = _create_property(USER_A, "Empty Property", "300 Empty St")

    body = _get_asset_summary(USER_A, tax_year=2023)
    assert len(body["properties"]) == 1
    row = body["properties"][0]
    assert row["property_id"] == prop["id"]
    assert row["asset_count"] == 0
    assert row["depreciation_total"] == "0.00"


# ============================================================================
# Auth (consistent with the other protected dashboard routes)
# ============================================================================


def test_asset_summary_requires_auth(wired):
    """GET /dashboard/assets is protected: no JWT claims → 401."""
    resp = handler(_event("GET", "/dashboard/assets"))  # no sub
    assert resp["statusCode"] == 401
    assert json.loads(resp["body"])["error"] == "unauthorized"
