"""Task 15.10: Loan routes through the real handler against moto DynamoDB + S3.

**Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.6, 8.7, 8.8**

Property 15: a missing and a foreign property yield the identical 404 on every
Loan route.
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
USER_SUB = "user-loan-1"
OTHER_SUB = "user-loan-2"
MONEY = re.compile(r"^\d+\.\d{2}$")


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
        s3.create_bucket(Bucket="logstead-files-loans")
        handler_module.configure(
            repo=DynamoRepository(ddb, TABLE_NAME),
            files=S3FileAdapter(s3, "logstead-files-loans"),
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


def _json(resp: dict):
    return json.loads(resp["body"])


def _loan_body(**over) -> dict:
    body = {
        "description": "Mortgage",
        "annual_interest_rate": "6.875",
        "monthly_payment": "1970.79",
        "anchor_balance": "214500.00",
        "anchor_date": "2025-06-01",
        "original_principal": "300000.00",
        "closing_date": "2022-02-14",
    }
    body.update(over)
    return body


def _make_property(sub: str = USER_SUB) -> str:
    resp = _call(
        "POST", "/properties", sub=sub, body={"name": "Maple", "address_text": "1 Maple"}
    )
    assert resp["statusCode"] == 201, resp["body"]
    return _json(resp)["id"]


def _make_loan(pid: str, **over) -> dict:
    resp = _call("POST", f"/properties/{pid}/loans", body=_loan_body(**over))
    assert resp["statusCode"] == 201, resp["body"]
    return _json(resp)


# --- create / list / get / update / delete ----------------------------------


def test_create_returns_201_with_anchor_fields(wired):
    pid = _make_property()
    resp = _call("POST", f"/properties/{pid}/loans", body=_loan_body())
    assert resp["statusCode"] == 201, resp["body"]
    loan = _json(resp)
    assert loan["id"]
    assert loan["property_id"] == pid
    for name in ("monthly_payment", "anchor_balance", "extra_principal", "original_principal"):
        assert isinstance(loan[name], str) and MONEY.match(loan[name]), name
    assert loan["monthly_payment"] == "1970.79"
    assert loan["anchor_balance"] == "214500.00"
    assert loan["anchor_date"] == "2025-06-01"
    assert loan["original_principal"] == "300000.00"
    assert loan["closing_date"] == "2022-02-14"
    assert isinstance(loan["annual_interest_rate"], str)
    assert loan["include_in_report"] is True
    assert loan["interest_overrides"] == {}
    # Derived fields.
    assert isinstance(loan["remaining_payments"], int) and loan["remaining_payments"] > 0
    assert loan["next_payment_date"] == "2025-07-01"
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", loan["projected_payoff_date"])
    assert loan["payoff_balance"] is None
    assert loan["status"] in ("active", "ended")
    # Removed fields are not returned.
    for name in (
        "term_months",
        "first_payment_date",
        "payment_override",
        "default_payment",
        "scheduled_payment",
    ):
        assert name not in loan, name


def test_create_without_informational_fields(wired):
    pid = _make_property()
    body = _loan_body()
    del body["original_principal"], body["closing_date"]
    resp = _call("POST", f"/properties/{pid}/loans", body=body)
    assert resp["statusCode"] == 201, resp["body"]
    loan = _json(resp)
    assert loan["original_principal"] is None
    assert loan["closing_date"] is None


def test_create_accepts_camel_case_keys(wired):
    pid = _make_property()
    resp = _call(
        "POST",
        f"/properties/{pid}/loans",
        body={
            "description": "Camel",
            "annualInterestRate": "5",
            "monthlyPayment": "1500.00",
            "anchorBalance": "100000.00",
            "anchorDate": "2024-01-15",
            "originalPrincipal": "120000.00",
        },
    )
    assert resp["statusCode"] == 201, resp["body"]
    loan = _json(resp)
    assert loan["anchor_balance"] == "100000.00"
    assert loan["anchor_date"] == "2024-01-15"
    assert loan["original_principal"] == "120000.00"


def test_legacy_origination_keys_do_not_satisfy_required_fields(wired):
    pid = _make_property()
    resp = _call(
        "POST",
        f"/properties/{pid}/loans",
        body={
            "description": "Old",
            "original_principal": "300000.00",
            "annual_interest_rate": "6.5",
            "term_months": 360,
            "first_payment_date": "2023-02-01",
        },
    )
    assert resp["statusCode"] == 400, resp["body"]
    fields = {e["field"] for e in _json(resp)["errors"]}
    assert {"monthly_payment", "anchor_balance", "anchor_date"} <= fields


def test_list_get_update_delete_round_trip(wired):
    pid = _make_property()
    loan = _make_loan(pid)
    lid = loan["id"]

    resp = _call("GET", f"/properties/{pid}/loans")
    assert resp["statusCode"] == 200
    assert [x["id"] for x in _json(resp)] == [lid]

    resp = _call("GET", f"/properties/{pid}/loans/{lid}")
    assert resp["statusCode"] == 200
    assert _json(resp)["id"] == lid

    resp = _call(
        "PUT",
        f"/properties/{pid}/loans/{lid}",
        body=_loan_body(description="Renamed", anchor_balance="200000.00"),
    )
    assert resp["statusCode"] == 200, resp["body"]
    updated = _json(resp)
    assert updated["id"] == lid
    assert updated["description"] == "Renamed"
    assert updated["anchor_balance"] == "200000.00"

    resp = _call("DELETE", f"/properties/{pid}/loans/{lid}")
    assert resp["statusCode"] == 200, resp["body"]

    resp = _call("GET", f"/properties/{pid}/loans/{lid}")
    assert resp["statusCode"] == 404
    resp = _call("GET", f"/properties/{pid}/loans")
    assert _json(resp) == []


def test_missing_loan_is_404_on_every_loan_route(wired):
    pid = _make_property()
    base = f"/properties/{pid}/loans/nope"
    calls = [
        ("GET", base, None),
        ("PUT", base, _loan_body()),
        ("DELETE", base, None),
        ("GET", f"{base}/schedule", None),
        ("PUT", f"{base}/interest-overrides/2025", {"interest": "1.00"}),
        ("DELETE", f"{base}/interest-overrides/2025", None),
    ]
    for method, path, body in calls:
        resp = _call(method, path, body=body)
        assert resp["statusCode"] == 404, (method, path, resp["body"])
        assert _json(resp)["message"] == "Loan not found."


# --- validation -------------------------------------------------------------


def test_validation_error_has_field_and_errors_list(wired):
    pid = _make_property()
    resp = _call(
        "POST",
        f"/properties/{pid}/loans",
        body=_loan_body(anchor_balance="0", monthly_payment="0"),
    )
    assert resp["statusCode"] == 400
    data = _json(resp)
    assert data["error"] == "validation"
    assert data["field"]
    errors = data["errors"]
    assert isinstance(errors, list) and len(errors) >= 2
    for entry in errors:
        assert set(entry) == {"field", "message"}
    fields = {e["field"] for e in errors}
    assert {"anchor_balance", "monthly_payment"} <= fields


def test_update_validation_error_is_400(wired):
    pid = _make_property()
    lid = _make_loan(pid)["id"]
    resp = _call(
        "PUT", f"/properties/{pid}/loans/{lid}", body=_loan_body(anchor_balance="0")
    )
    assert resp["statusCode"] == 400
    assert _json(resp)["field"]


@pytest.mark.parametrize(
    "field",
    [
        "original_principal",
        "annual_interest_rate",
        "monthly_payment",
        "anchor_balance",
        "extra_principal",
    ],
)
def test_float_money_and_rate_rejected_on_create_and_update(wired, field):
    pid = _make_property()
    lid = _make_loan(pid)["id"]
    bad = _loan_body(**{field: 1000.5})
    resp = _call("POST", f"/properties/{pid}/loans", body=bad)
    assert resp["statusCode"] == 400, resp["body"]
    assert _json(resp)["field"] == field
    resp = _call("PUT", f"/properties/{pid}/loans/{lid}", body=bad)
    assert resp["statusCode"] == 400, resp["body"]
    assert _json(resp)["field"] == field


def test_payment_not_exceeding_first_month_interest_is_rejected(wired):
    pid = _make_property()
    resp = _call(
        "POST",
        f"/properties/{pid}/loans",
        body=_loan_body(monthly_payment="1228.91"),
    )
    assert resp["statusCode"] == 400, resp["body"]
    assert _json(resp)["field"] == "monthly_payment"


def test_invalid_anchor_date_is_rejected(wired):
    pid = _make_property()
    for bad in ("1899-12-31", "2025-02-30", "06/01/2025"):
        resp = _call(
            "POST", f"/properties/{pid}/loans", body=_loan_body(anchor_date=bad)
        )
        assert resp["statusCode"] == 400, (bad, resp["body"])
        assert _json(resp)["field"] == "anchor_date"


# --- schedule ---------------------------------------------------------------


def test_schedule_shape_and_money_strings(wired):
    pid = _make_property()
    loan = _make_loan(pid)
    lid = loan["id"]
    resp = _call("GET", f"/properties/{pid}/loans/{lid}/schedule")
    assert resp["statusCode"] == 200, resp["body"]
    sched = _json(resp)
    assert sched["loan_id"] == lid
    assert sched["estimate"] is True
    assert len(sched["payments"]) == loan["remaining_payments"]
    assert sched["payments"][0]["date"] == "2025-07-01"
    assert sched["yearly"][0]["tax_year"] == 2025
    row = sched["yearly"][0]
    for name in ("interest", "estimated_interest", "principal", "total_paid", "ending_balance"):
        assert isinstance(row[name], str) and MONEY.match(row[name]), name
    assert row["interest_override"] is None
    assert row["variance"] is None
    # No payoff date on this loan, so there is no payoff balance.
    assert sched["payoff_balance"] is None


# --- overrides --------------------------------------------------------------


def test_override_set_then_clear(wired):
    pid = _make_property()
    lid = _make_loan(pid)["id"]
    path = f"/properties/{pid}/loans/{lid}/interest-overrides/2025"

    before = _json(_call("GET", f"/properties/{pid}/loans/{lid}/schedule"))
    est = next(y for y in before["yearly"] if y["tax_year"] == 2025)["interest"]

    resp = _call("PUT", path, body={"interest": "12345.67"})
    assert resp["statusCode"] == 200, resp["body"]
    row = _json(resp)
    assert row["tax_year"] == 2025
    assert row["interest_override"] == "12345.67"
    assert row["interest"] == "12345.67"
    assert row["estimated_interest"] == est
    assert re.match(r"^-?\d+\.\d{2}$", row["variance"])

    loan = _json(_call("GET", f"/properties/{pid}/loans/{lid}"))
    assert loan["interest_overrides"] == {"2025": "12345.67"}

    resp = _call("DELETE", path)
    assert resp["statusCode"] == 200, resp["body"]
    cleared = _json(resp)
    assert cleared["interest_override"] is None
    assert cleared["variance"] is None
    assert cleared["interest"] == est

    loan = _json(_call("GET", f"/properties/{pid}/loans/{lid}"))
    assert loan["interest_overrides"] == {}


def test_override_validation_errors(wired):
    pid = _make_property()
    lid = _make_loan(pid)["id"]
    path = f"/properties/{pid}/loans/{lid}/interest-overrides/2025"

    for body in ({"interest": 12.5}, {"interest": "-1"}, {"interest": "1.234"}, {}):
        resp = _call("PUT", path, body=body)
        assert resp["statusCode"] == 400, (body, resp["body"])
        assert _json(resp)["field"]

    # Years before 1900 and years after the anchor year without payments
    # are rejected, naming the year.
    for year in (1899, 2090):
        resp = _call(
            "PUT",
            f"/properties/{pid}/loans/{lid}/interest-overrides/{year}",
            body={"interest": "1.00"},
        )
        assert resp["statusCode"] == 400, (year, resp["body"])
        assert _json(resp)["field"] == f"interest_overrides.{year}"


def test_override_allowed_from_1900_through_anchor_year(wired):
    pid = _make_property()
    lid = _make_loan(pid)["id"]  # anchor year 2025
    for year in (1900, 2023):
        path = f"/properties/{pid}/loans/{lid}/interest-overrides/{year}"
        resp = _call("PUT", path, body={"interest": "20650.12"})
        assert resp["statusCode"] == 200, (year, resp["body"])
        row = _json(resp)
        assert row["tax_year"] == year
        assert row["payments"] == 0
        assert row["interest"] == "20650.12"
        assert row["interest_override"] == "20650.12"
        assert row["estimated_interest"] == "0.00"
        assert row["variance"] == "20650.12"
        assert row["principal"] == "0.00"
        assert row["total_paid"] == "0.00"
        assert row["ending_balance"] is None

    loan = _json(_call("GET", f"/properties/{pid}/loans/{lid}"))
    assert loan["interest_overrides"] == {"1900": "20650.12", "2023": "20650.12"}

    sched = _json(_call("GET", f"/properties/{pid}/loans/{lid}/schedule"))
    years = [y["tax_year"] for y in sched["yearly"]]
    assert years == sorted(years)
    assert years[:2] == [1900, 2023]
    assert sched["yearly"][0]["ending_balance"] is None
    # Generated rows keep a balance, and payments are unchanged.
    assert sched["yearly"][2]["tax_year"] == 2025
    assert MONEY.match(sched["yearly"][2]["ending_balance"])
    assert len(sched["payments"]) == loan["remaining_payments"]

    # Clearing an override-only year removes its row.
    resp = _call(
        "DELETE", f"/properties/{pid}/loans/{lid}/interest-overrides/2023"
    )
    assert resp["statusCode"] == 200, resp["body"]
    sched = _json(_call("GET", f"/properties/{pid}/loans/{lid}/schedule"))
    assert [y["tax_year"] for y in sched["yearly"]][:2] == [1900, 2025]


# --- Property 15: missing and foreign property are indistinguishable --------


def _all_loan_calls(pid: str, lid: str):
    base = f"/properties/{pid}/loans"
    return [
        ("POST", base, _loan_body()),
        ("GET", base, None),
        ("GET", f"{base}/line-12-impact", None),
        ("GET", f"{base}/{lid}", None),
        ("PUT", f"{base}/{lid}", _loan_body()),
        ("DELETE", f"{base}/{lid}", None),
        ("GET", f"{base}/{lid}/schedule", None),
        ("PUT", f"{base}/{lid}/interest-overrides/2025", {"interest": "1.00"}),
        ("DELETE", f"{base}/{lid}/interest-overrides/2025", None),
    ]


def test_missing_and_foreign_property_return_identical_404(wired):
    pid = _make_property()
    lid = _make_loan(pid)["id"]

    foreign = _all_loan_calls(pid, lid)
    missing = _all_loan_calls("no-such-property", lid)
    for (method, fpath, fbody), (_, mpath, mbody) in zip(foreign, missing):
        f = _call(method, fpath, sub=OTHER_SUB, body=fbody)
        m = _call(method, mpath, sub=OTHER_SUB, body=mbody)
        assert f["statusCode"] == 404, (method, fpath, f["body"])
        assert m["statusCode"] == 404, (method, mpath, m["body"])
        assert f["body"] == m["body"], (method, fpath)
        assert _json(f)["message"] == "Property not found."

    # The owner's loan is untouched by the foreign attempts.
    resp = _call("GET", f"/properties/{pid}/loans/{lid}")
    assert resp["statusCode"] == 200


# --- line 12 impact ---------------------------------------------------------


def test_line12_impact_route_returns_list(wired):
    pid = _make_property()
    _make_loan(pid)
    resp = _call("GET", f"/properties/{pid}/loans/line-12-impact")
    assert resp["statusCode"] == 200
    assert _json(resp) == []
