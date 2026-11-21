"""Task 3.1: wire contract for the carryforward chain status (drift, carried_from_year).

Drives the real router over moto (as ``test_carryforward_money_property.py``
does) and inspects the serialized ``GET /carryforward`` body.

* Example (carry-in semantics): the worked example returns ``carried`` with
  ``carried_from_year`` 2016 and ``drift`` ``"-5000.00"``; an unreported year
  returns null ``drift`` and null ``carried_from_year``.
* Property 9: every year carries ``drift`` (``^-?\\d+\\.\\d{2}$`` or null) and
  ``carried_from_year`` (int or null, strictly below ``tax_year``), ``status``
  is one of the four values, and existing fields keep their shape.
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
BUCKET = "logstead-files-carryforward-chain"
REGION = "us-east-1"
USER = "user-carryforward-chain"

_MONEY_RE = re.compile(r"^-?\d+\.\d{2}$")
_STATUSES = frozenset({"ok", "mismatch", "carried", "unreported"})
_EXISTING_FIELDS = (
    "tax_year",
    "schedule_e_net",
    "expected_carryforward",
    "reported_carryforward",
    "allowed_loss",
    "fully_allowed",
    "status",
)


@contextlib.contextmanager
def _moto_wiring():
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
        handler_module.configure(
            repo=DynamoRepository(ddb, TABLE_NAME), files=S3FileAdapter(s3, BUCKET)
        )
        try:
            yield
        finally:
            handler_module.reset_wiring()


def _event(method: str, path: str, body: dict | None = None) -> dict:
    event: dict = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {
                "jwt": {"claims": {"sub": USER, "cognito:username": f"{USER}@example.com"}}
            },
        },
        "rawPath": path,
    }
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _create_property() -> str:
    resp = handler(_event("POST", "/properties", {"name": "P", "address_text": "1 Main St"}))
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])["id"]


def _seed_net(property_id: str, year: int, net: Decimal) -> None:
    """Seed one transaction so the year's Schedule E net is exactly ``net``."""
    if net == 0:
        return
    body = {
        "date": f"{year:04d}-06-15",
        "amount": str(abs(net)),
        "type": "income" if net > 0 else "expense",
        "category_id": "rents-received" if net > 0 else "repairs",
    }
    resp = handler(_event("POST", f"/properties/{property_id}/transactions", body))
    assert resp["statusCode"] == 201, resp["body"]


def _set_reported(year: int, amount: str) -> None:
    resp = handler(_event("PUT", f"/carryforward/years/{year}", {"amount": amount}))
    assert resp["statusCode"] == 200, resp["body"]


def _get() -> dict:
    resp = handler(_event("GET", "/carryforward"))
    assert resp["statusCode"] == 200, resp["body"]
    return json.loads(resp["body"])


def _assert_wire_year(entry: dict) -> None:
    for field in _EXISTING_FIELDS + ("drift", "carried_from_year", "expected_carry_in"):
        assert field in entry, f"missing {field}"
    assert entry["status"] in _STATUSES
    drift = entry["drift"]
    if drift is not None:
        assert isinstance(drift, str) and _MONEY_RE.match(drift), drift
    cf = entry["carried_from_year"]
    if cf is not None:
        assert isinstance(cf, int) and not isinstance(cf, bool)
        assert cf < entry["tax_year"]
    # drift null iff unreported; carried_from_year only on carried years.
    assert (drift is None) == (entry["reported_carryforward"] is None)
    if entry["status"] != "carried":
        assert cf is None
    for money in ("schedule_e_net", "expected_carry_in", "expected_carryforward", "allowed_loss"):
        assert isinstance(entry[money], str) and _MONEY_RE.match(entry[money])
    assert isinstance(entry["fully_allowed"], bool)


def test_worked_example_over_the_wire() -> None:
    nets = {
        2014: Decimal("-10000.00"),
        2015: Decimal("-2000.00"),
        2016: Decimal("-1000.00"),
        2017: Decimal("1500.00"),
        2018: Decimal("-500.00"),
        2019: Decimal("-100.00"),
    }
    # Reported = Form 8582 "Prior years unallowed losses" (carry-IN) per year.
    # Expected carry-in / carry-out (opening 0.00):
    #   2014: 0 -> 10000   2015: 10000 -> 12000   2016: 12000 -> 13000
    #   2017: 13000 -> 11500   2018: 11500 -> 12000   2019: 12000 -> 12100
    reported = {
        2014: "0.00",  # equals the opening balance -> ok
        2015: "10000.00",  # equals 2014's carry-out -> ok
        2016: "7000.00",  # wrong (expected 12000; chain 10000+2000=12000) -> mismatch
        2017: "8000.00",  # chain: 7000 + 1000 = 8000 -> carried from 2016
        2018: "6500.00",  # chain: 8000 - 1500 = 6500 -> carried from 2016
    }  # 2019 left unreported
    with _moto_wiring():
        pid = _create_property()
        for year, net in nets.items():
            _seed_net(pid, year, net)
        for year, amount in reported.items():
            _set_reported(year, amount)
        body = _get()

    by_year = {y["tax_year"]: y for y in body["years"]}
    for entry in body["years"]:
        _assert_wire_year(entry)

    for year in (2014, 2015):
        assert by_year[year]["status"] == "ok"
        assert by_year[year]["drift"] == "0.00"
        assert by_year[year]["carried_from_year"] is None
    assert by_year[2016]["status"] == "mismatch"
    assert by_year[2016]["drift"] == "-5000.00"
    assert by_year[2016]["carried_from_year"] is None
    for year in (2017, 2018):
        assert by_year[year]["status"] == "carried"
        assert by_year[year]["carried_from_year"] == 2016
        assert by_year[year]["drift"] == "-5000.00"
    # expected_carry_in on every year (carry-out of the previous year).
    assert {y: by_year[y]["expected_carry_in"] for y in by_year} == {
        2014: "0.00",
        2015: "10000.00",
        2016: "12000.00",
        2017: "13000.00",
        2018: "11500.00",
        2019: "12000.00",
    }
    # Existing fields unchanged (expected_carryforward is still the carry-out).
    assert by_year[2016]["expected_carryforward"] == "13000.00"
    assert by_year[2016]["reported_carryforward"] == "7000.00"
    assert by_year[2016]["schedule_e_net"] == "-1000.00"
    # Summary: next year after the latest data year and its expected carry-in.
    assert body["next_year"] == 2020
    assert type(body["next_year"]) is int
    assert body["next_year_expected_carry_in"] == "12100.00"
    # Unreported year: null drift, null carried_from_year.
    assert by_year[2019]["status"] == "unreported"
    assert by_year[2019]["drift"] is None
    assert by_year[2019]["carried_from_year"] is None
    # Raw JSON carries carried_from_year as an integer, not a string/float.
    assert type(by_year[2017]["carried_from_year"]) is int


_YEARS = [2018, 2019, 2021, 2022, 2023]
_nets = st.decimals(
    min_value=Decimal("-5000.00"),
    max_value=Decimal("5000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
# Per year: None (unreported), or a delta in cents applied to a base reported value.
_reported_choice = st.one_of(
    st.none(),
    st.decimals(
        min_value=Decimal("0.00"),
        max_value=Decimal("20000.00"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
)


# Feature: carryforward-chain-status, Property 9: Wire figures are fixed-format
# and never float
@settings(deadline=None, max_examples=100)
@given(
    nets=st.lists(_nets, min_size=len(_YEARS), max_size=len(_YEARS)),
    reported=st.lists(_reported_choice, min_size=len(_YEARS), max_size=len(_YEARS)),
    chain_follow=st.booleans(),
)
def test_wire_chain_fields_are_fixed_format(
    nets: list[Decimal], reported: list[Decimal | None], chain_follow: bool
) -> None:
    """Validates: Requirements 1.6, 6.2, 6.3, 6.4, 10.1"""
    with _moto_wiring():
        pid = _create_property()
        for year, net in zip(_YEARS, nets):
            _seed_net(pid, year, net)
        if chain_follow:
            # Build reported values by chaining each year's step from the prior
            # reported figure so `carried` years are exercised over the wire.
            prior = Decimal("0.00")
            for index, (year, net) in enumerate(zip(_YEARS, nets)):
                start = reported[index]
                if start is not None and index == 0:
                    prior = start  # injected first-year error
                elif index > 0 or start is None:
                    prior = (prior + (-net)) if net < 0 else max(prior - net, Decimal("0.00"))
                _set_reported(year, str(prior))
        else:
            for year, value in zip(_YEARS, reported):
                if value is not None:
                    _set_reported(year, str(value))
        body = _get()
        raw = json.dumps(body)

    if body["years"]:
        assert "carried_from_year" in raw and "drift" in raw
    data_years = {y for y, n in zip(_YEARS, nets) if n != 0}
    assert data_years <= {e["tax_year"] for e in body["years"]}
    for entry in body["years"]:
        _assert_wire_year(entry)

    # Property 9 (carry-in semantics): summary figures are fixed-format, never float.
    next_year = body["next_year"]
    nyc = body["next_year_expected_carry_in"]
    assert isinstance(nyc, str) and _MONEY_RE.match(nyc), nyc
    tolerance = body["status_tolerance"]
    assert isinstance(tolerance, str) and re.match(r"^\d+\.\d{2}$", tolerance), tolerance
    assert tolerance == "2.00"
    if body["years"]:
        assert type(next_year) is int
        assert next_year == body["years"][-1]["tax_year"] + 1
        assert nyc == body["years"][-1]["expected_carryforward"]
    else:
        assert next_year is None
    # Each year enters with the previous year's carry-out.
    for prev, cur in zip(body["years"], body["years"][1:]):
        assert cur["expected_carry_in"] == prev["expected_carryforward"]
