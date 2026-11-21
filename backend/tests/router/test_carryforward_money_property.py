"""Property-based test: every carryforward figure serializes as a two-decimal string.

Design Property 9 (Requirements 1.4, 2.6, 3.6): *for any* generated portfolio and
set of user-entered carryforward inputs, every monetary field in the serialized
JSON body of ``GET /carryforward`` (after the router's ``_to_jsonable``) is a JSON
string matching ``^-?\\d+\\.\\d{2}$`` — each reconciled year's ``schedule_e_net``
and ``expected_carryforward``, every non-null ``reported_carryforward``, and the
top-level ``opening_balance`` — and no monetary field is serialized as a
floating-point value or a DynamoDB ``Number``. Only ``tax_year`` is an integer,
and ``status`` is one of the three known literals.

This drives the real router as an integration boundary (mirroring
``test_trends_money_property.py``): a ``moto``-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket are wired via
``handler_module.configure(...)``, a portfolio is seeded through the public
``POST`` endpoints (properties + income/expense transactions dated across
several deliberately non-contiguous tax years), an optional per-year
Reported_Carryforward and an optional Opening_Balance are set via the
carryforward ``PUT`` routes, and the serialized ``GET /carryforward`` body is
parsed back from JSON so money fields can be inspected as the wire actually
carries them.

Hypothesis generates ``1..k`` properties, each with an arbitrary mix of income
and expense transactions dated across a spread of distinct (deliberately
non-contiguous) tax years, so the reconciliation spans several Data_Years with a
mix of loss and gain years. Each example provisions its own isolated moto
resources; per-example provisioning is not instantaneous, so the deadline is
disabled and the example count is held at 100 to keep the moto-backed run
reasonable.
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
BUCKET = "logstead-files-carryforward-money"
REGION = "us-east-1"
USER = "user-carryforward-money"

#: Two-decimal money string, e.g. "0.00", "1250.00", "-3.50" (Req 1.4, 2.6, 3.6).
_MONEY_RE = re.compile(r"^-?\d+\.\d{2}$")

#: The four known Reconciliation_Status literals (Req 2.5, 6.4).
_STATUSES = frozenset({"ok", "mismatch", "carried", "unreported"})

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


def _set_reported(tax_year: int, amount: str) -> None:
    resp = handler(
        _event("PUT", f"/carryforward/years/{tax_year}", sub=USER)
        | {"body": json.dumps({"amount": amount})}
    )
    assert resp["statusCode"] == 200, resp["body"]


def _set_opening_balance(amount: str) -> None:
    resp = handler(
        _event("PUT", "/carryforward/opening-balance", sub=USER)
        | {"body": json.dumps({"amount": amount})}
    )
    assert resp["statusCode"] == 200, resp["body"]


def _get_carryforward() -> dict:
    """GET /carryforward → assert 200 and parse the serialized JSON body."""
    resp = handler(_event("GET", "/carryforward", sub=USER))
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


# A property is a list of transactions spread across the tax years.
_property_spec = st.lists(_txn(), min_size=0, max_size=8)

# An optional opening balance seeds the earliest reconciled year so the
# top-level opening_balance exercises a non-zero path too.
_opening_balance = st.one_of(st.none(), st.just("12500.00"), st.just("0.00"))

# Optional per-year reported values so non-null reported_carryforward fields are
# exercised. Each generated (year, amount) is PUT via the carryforward route.
_reported_entry = st.tuples(st.sampled_from(_TAX_YEARS), _amounts)


def _iso_date(year: int, index: int) -> str:
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _assert_money(label: str, value: object) -> None:
    """A money field must be a two-decimal string, never a float/number."""
    assert isinstance(value, str), f"{label} is not a string: {value!r} ({type(value)})"
    assert not isinstance(value, bool)
    assert _MONEY_RE.match(value), f"{label} is not a two-decimal money string: {value!r}"


# Feature: passive-loss-carryforward, Property 9: Every figure is a two-decimal
# money string — never a float or Number
@settings(deadline=None, max_examples=100)
@given(
    properties=st.lists(_property_spec, min_size=1, max_size=3),
    opening_balance=_opening_balance,
    reported=st.lists(_reported_entry, min_size=0, max_size=4),
)
def test_carryforward_every_money_field_is_two_decimal_string(
    properties: list[list[tuple[str, str, Decimal, str | None, int]]],
    opening_balance: str | None,
    reported: list[tuple[int, Decimal]],
) -> None:
    """Every money figure in the serialized carryforward JSON is a two-decimal string.

    Validates: Requirements 1.4, 2.6, 3.6
    """
    with _moto_wiring():
        for p_index, txns in enumerate(properties):
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

        if opening_balance is not None:
            _set_opening_balance(opening_balance)

        # Set per-year reported values (last write wins per year, matching the
        # route's replace semantics).
        for year, amount in reported:
            _set_reported(year, str(amount))

        summary = _get_carryforward()

        # The top-level opening_balance is always a two-decimal money string.
        _assert_money("summary.opening_balance", summary["opening_balance"])

        # has_data is a bool, never a money/number.
        assert isinstance(summary["has_data"], bool)

        # next_year is an int or null (never a bool/str); its carry-in is money.
        next_year = summary["next_year"]
        assert next_year is None or (
            isinstance(next_year, int) and not isinstance(next_year, bool)
        )
        _assert_money(
            "summary.next_year_expected_carry_in", summary["next_year_expected_carry_in"]
        )
        assert (next_year is None) == (len(summary["years"]) == 0)

        # status_tolerance is a fixed two-decimal string, never a float.
        assert isinstance(summary["status_tolerance"], str)
        assert re.match(r"^\d+\.\d{2}$", summary["status_tolerance"])

        years = summary["years"]
        assert isinstance(years, list)
        for year_entry in years:
            # tax_year is the ONLY numeric field, and it is an int.
            assert isinstance(year_entry["tax_year"], int)
            assert not isinstance(year_entry["tax_year"], bool)

            # status is one of the three known literals.
            assert year_entry["status"] in _STATUSES

            # Derived + running money figures.
            _assert_money("year.schedule_e_net", year_entry["schedule_e_net"])
            _assert_money(
                "year.expected_carryforward", year_entry["expected_carryforward"]
            )
            # Carry-in semantics: expected_carry_in is on every year.
            _assert_money("year.expected_carry_in", year_entry["expected_carry_in"])

            # reported_carryforward is either null or a two-decimal money string.
            reported_value = year_entry["reported_carryforward"]
            if reported_value is not None:
                _assert_money("year.reported_carryforward", reported_value)
