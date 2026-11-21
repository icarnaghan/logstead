"""Property-based test: every trend figure serializes as a two-decimal string.

Design Property 6 (Requirements 7.1, 7.2): *for any* generated Trends_Series,
every monetary field in the serialized JSON body of ``GET /dashboard/trends``
(after the router's ``_to_jsonable``) is a JSON string matching
``^-?\\d+\\.\\d{2}$`` — the portfolio ``total_income`` / ``total_expenses`` /
``net`` / ``depreciation_total`` on each year, and every per-property point's
``total_income`` / ``total_expenses`` / ``net`` — and no monetary field is
serialized as a floating-point value or a DynamoDB ``Number``. Only ``tax_year``
is an integer.

This drives the real router as an integration boundary (mirroring
``test_dashboard_assets_route.py``): a ``moto``-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket are wired via
``handler_module.configure(...)``, portfolios are seeded through the public
``POST`` endpoints, and the serialized ``GET /dashboard/trends`` body is parsed
back from JSON so money fields can be inspected as the wire actually carries
them.

Hypothesis generates ``1..k`` properties, each with an arbitrary mix of income
and expense transactions dated across several distinct (deliberately
non-contiguous) tax years, plus an optional depreciable asset so the
``depreciation_total`` field exercises a non-zero path too. Each example
provisions its own isolated moto resources; per-example provisioning is not
instantaneous, so the deadline is disabled and the example count is held at 100
to keep the moto-backed run reasonable.
"""

from __future__ import annotations

import contextlib
import json
import re
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import handler

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-trends-money"
REGION = "us-east-1"
USER = "user-trends-money"

#: Two-decimal money string, e.g. "0.00", "1250.00", "-3.50" (Req 7.1).
_MONEY_RE = re.compile(r"^-?\d+\.\d{2}$")

# Deliberately non-contiguous tax years so the series spans several Data_Years.
_TAX_YEARS = [2020, 2022, 2023, 2025]


@contextlib.contextmanager
def _moto_wiring():
    """Provision isolated moto resources and wire the handler against them."""
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
        repo = DynamoRepository(ddb, TABLE_NAME)
        handler_module.configure(repo=repo, files=S3FileAdapter(s3, BUCKET))
        try:
            yield
        finally:
            handler_module.reset_wiring()


# --- event / request helpers -------------------------------------------------


def _claims(sub: str) -> dict:
    return {"sub": sub, "cognito:username": f"{sub}@example.com"}


def _event(method: str, path: str, *, sub: str | None = None):
    event: dict = {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
    }
    if sub is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": _claims(sub)}}
    return event


def _create_property(name: str) -> str:
    resp = handler(
        _event("POST", "/properties", sub=USER)
        | {"body": json.dumps({"name": name, "address_text": f"{name} St"})}
    )
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])["id"]


def _create_transaction(property_id: str, body: dict) -> None:
    resp = handler(
        _event("POST", f"/properties/{property_id}/transactions", sub=USER)
        | {"body": json.dumps(body)}
    )
    assert resp["statusCode"] == 201, resp["body"]


def _create_asset(property_id: str, cost_basis: str, placed_in_service: str) -> None:
    resp = handler(
        _event("POST", f"/properties/{property_id}/assets", sub=USER)
        | {
            "body": json.dumps(
                {
                    "description": "HVAC",
                    "cost_basis": cost_basis,
                    "placed_in_service_date": placed_in_service,
                }
            )
        }
    )
    assert resp["statusCode"] == 201, resp["body"]


def _get_trends() -> dict:
    """GET /dashboard/trends → assert 200 and parse the serialized JSON body."""
    resp = handler(_event("GET", "/dashboard/trends", sub=USER))
    assert resp["statusCode"] == 200, resp["body"]
    return json.loads(resp["body"])


# --- strategies --------------------------------------------------------------

_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# (type, category_id) pairs across a spread of Schedule E lines. "other"
# (Line 19) requires a non-blank description, supplied by the generator.
_INCOME_SPECS = [("income", "rents-received"), ("income", "royalties-received")]
_EXPENSE_SPECS = [
    ("expense", "repairs"),
    ("expense", "utilities"),
    ("expense", "other"),
]


@st.composite
def _txn(draw: st.DrawFn) -> tuple[str, str, Decimal, str | None, int]:
    ttype, category = draw(st.sampled_from(_INCOME_SPECS + _EXPENSE_SPECS))
    amount = draw(_amounts)
    year = draw(st.sampled_from(_TAX_YEARS))
    description: str | None = None
    if category == "other":
        description = draw(st.text(min_size=1, max_size=20).filter(lambda s: s.strip()))
    return ttype, category, amount, description, year


# A property = (list of transactions, optional asset cost basis). A non-None
# cost basis seeds a depreciable asset so depreciation_total exercises a
# non-zero path.
_property_spec = st.tuples(
    st.lists(_txn(), min_size=0, max_size=8),
    st.one_of(st.none(), st.just("27500.00")),
)


def _iso_date(year: int, index: int) -> str:
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _assert_money(label: str, value: object) -> None:
    """A money field must be a two-decimal string, never a float/number."""
    assert isinstance(value, str), f"{label} is not a string: {value!r} ({type(value)})"
    assert not isinstance(value, bool)
    assert _MONEY_RE.match(value), f"{label} is not a two-decimal money string: {value!r}"


# Feature: dashboard-year-over-year-trends, Property 6: Every figure is a
# two-decimal money string — never a float or Number
@settings(deadline=None, max_examples=100)
@given(properties=st.lists(_property_spec, min_size=1, max_size=3))
def test_trends_every_money_field_is_two_decimal_string(
    properties: list[tuple[list[tuple[str, str, Decimal, str | None, int]], str | None]],
) -> None:
    """Every money figure in the serialized trends JSON is a two-decimal string.

    Validates: Requirements 7.1, 7.2
    """
    with _moto_wiring():
        for p_index, (txns, cost_basis) in enumerate(properties):
            pid = _create_property(f"Prop{p_index}")
            for t_index, (ttype, category, amount, description, year) in enumerate(txns):
                body: dict = {
                    "date": _iso_date(year, t_index),
                    "amount": str(amount),
                    "type": ttype,
                    "category_id": category,
                }
                if description is not None:
                    body["description"] = description
                _create_transaction(pid, body)
            if cost_basis is not None:
                _create_asset(pid, cost_basis, "2020-01-10")

        trends = _get_trends()

        years = trends["years"]
        assert isinstance(years, list)
        for year_entry in years:
            # tax_year is the ONLY numeric field, and it is an int.
            assert isinstance(year_entry["tax_year"], int)
            assert not isinstance(year_entry["tax_year"], bool)

            # Portfolio-level money figures.
            _assert_money("year.total_income", year_entry["total_income"])
            _assert_money("year.total_expenses", year_entry["total_expenses"])
            _assert_money("year.net", year_entry["net"])
            _assert_money("year.depreciation_total", year_entry["depreciation_total"])

            # Per-property money figures.
            for point in year_entry["properties"]:
                _assert_money("point.total_income", point["total_income"])
                _assert_money("point.total_expenses", point["total_expenses"])
                _assert_money("point.net", point["net"])
