"""Task 4.2: input-validation and error-response audit tests.

Every malformed input below used to produce a 500 (or, for the huge recovery
period, a hang) or was silently accepted. Each must now be a clean 4xx using the
standard error shape, and no response may leak internals.
"""
from __future__ import annotations

import json

import pytest

from tests.router.test_cross_user_authorization import (  # noqa: F401 - fixtures
    _call,
    aws,
    env,
)

USER = "validation-user"
BIG = "x" * 20_000


@pytest.fixture
def pid(env):  # noqa: F811
    status, body = _call(
        USER,
        "POST",
        "/properties",
        body={"name": "P", "address_text": "1 Main St", "property_type": "single_family"},
    )
    assert status == 201, body
    return body["id"]


def _assert_clean_error(status, body, expected=400):
    assert status == expected, body
    assert set(body) >= {"error", "message"}
    text = json.dumps(body)
    for leak in ("Traceback", "Logstead", "botocore", "Exception", "dynamodb"):
        assert leak not in text


# --- Property / business / transaction field types --------------------------


@pytest.mark.parametrize("bad", [123, [], {}, True])
def test_property_text_fields_reject_non_strings(env, pid, bad):  # noqa: F811
    payload = {"name": bad, "address_text": "a", "property_type": "single_family"}
    status, body = _call(USER, "POST", "/properties", body=payload)
    _assert_clean_error(status, body)
    assert body["field"] == "name"
    status, body = _call(USER, "PUT", f"/properties/{pid}", body=payload)
    _assert_clean_error(status, body)


@pytest.mark.parametrize("bad", [123, [], {}])
def test_business_text_fields_reject_non_strings(env, bad):  # noqa: F811
    status, body = _call(
        USER, "POST", "/businesses", body={"legal_name": bad, "entity_type": "llc"}
    )
    _assert_clean_error(status, body)
    assert body["field"] == "legal_name"


@pytest.mark.parametrize(
    "amount", ["NaN", "Infinity", "-Infinity", "1e400", 1e30, "abc", True, [], {}]
)
def test_transaction_amount_rejects_non_finite_huge_and_wrong_types(env, pid, amount):  # noqa: F811
    status, body = _call(
        USER,
        "POST",
        f"/properties/{pid}/transactions",
        body={"date": "2024-01-01", "amount": amount, "type": "expense", "category_id": "x"},
    )
    _assert_clean_error(status, body)


@pytest.mark.parametrize("field", ["date", "type", "category_id", "description"])
def test_transaction_text_fields_reject_non_strings(env, pid, field):  # noqa: F811
    payload = {"date": "2024-01-01", "amount": "1.00", "type": "expense", "category_id": "x"}
    payload[field] = 5
    status, body = _call(USER, "POST", f"/properties/{pid}/transactions", body=payload)
    _assert_clean_error(status, body)
    assert body["field"] == field


# --- Assets -------------------------------------------------------------------


def _asset(**over):
    base = {
        "description": "d",
        "cost_basis": "100",
        "placed_in_service_date": "2024-01-01",
        "recovery_period_years": "27.5",
    }
    base.update(over)
    return base


@pytest.mark.parametrize("period", ["abc", [], {}, True, "NaN", "Infinity", "-1"])
def test_asset_recovery_period_invalid(env, pid, period):  # noqa: F811
    status, body = _call(
        USER, "POST", f"/properties/{pid}/assets", body=_asset(recovery_period_years=period)
    )
    _assert_clean_error(status, body)


@pytest.mark.parametrize("period", ["51", "100", "1e30", "1e400"])
def test_asset_recovery_period_is_bounded(env, pid, period):  # noqa: F811
    """An unbounded period made the schedule engine loop for ceil(period) rows."""
    status, body = _call(
        USER, "POST", f"/properties/{pid}/assets", body=_asset(recovery_period_years=period)
    )
    _assert_clean_error(status, body)


def test_asset_recovery_period_at_limit_is_accepted(env, pid):  # noqa: F811
    status, body = _call(
        USER, "POST", f"/properties/{pid}/assets", body=_asset(recovery_period_years="50")
    )
    assert status == 201, body


@pytest.mark.parametrize("year", ["abc", "1e3", "99999999999999999999999"])
def test_asset_override_year_must_be_an_integer(env, pid, year):  # noqa: F811
    status, body = _call(
        USER,
        "POST",
        f"/properties/{pid}/assets",
        body=_asset(depreciation_overrides={year: "5.00"}),
    )
    _assert_clean_error(status, body)


# --- Loans --------------------------------------------------------------------


def _loan(**over):
    base = {
        "description": "L",
        "annual_interest_rate": "5",
        "monthly_payment": "100",
        "anchor_balance": "1000",
        "anchor_date": "2024-01-01",
    }
    base.update(over)
    return base


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e400", [], {}])
def test_loan_decimals_reject_non_finite_huge_and_wrong_types(env, pid, value):  # noqa: F811
    status, body = _call(
        USER, "POST", f"/properties/{pid}/loans", body=_loan(anchor_balance=value)
    )
    _assert_clean_error(status, body)
    assert body["field"] == "anchor_balance"


def test_loan_include_in_report_must_be_boolean(env, pid):  # noqa: F811
    status, body = _call(
        USER, "POST", f"/properties/{pid}/loans", body=_loan(include_in_report="yes")
    )
    _assert_clean_error(status, body)
    assert body["field"] == "include_in_report"


@pytest.mark.parametrize("value", [123, [], {}])
def test_loan_dates_reject_non_strings(env, pid, value):  # noqa: F811
    status, body = _call(
        USER, "POST", f"/properties/{pid}/loans", body=_loan(anchor_date=value)
    )
    _assert_clean_error(status, body)
    assert body["field"] == "anchor_date"


# --- Numbers in path, query and body ------------------------------------------


@pytest.mark.parametrize("year", ["abc", "1e3", "1_000", "1899", "2201", "99999999999999999999"])
def test_tax_year_query_must_be_in_range(env, pid, year):  # noqa: F811
    status, body = _call(
        USER, "GET", f"/properties/{pid}/report", query={"taxYear": year}
    )
    _assert_clean_error(status, body)
    assert body["field"] == "taxYear"


@pytest.mark.parametrize("year", ["abc", "0", "-1", "99999999999"])
def test_tax_year_path_must_be_in_range(env, year):  # noqa: F811
    status, body = _call(USER, "PUT", f"/carryforward/years/{year}", body={"amount": "1"})
    _assert_clean_error(status, body)


@pytest.mark.parametrize("days", [10**30, -1, "abc", 1.5, True, None])
def test_usage_days_must_be_valid_day_counts(env, pid, days):  # noqa: F811
    status, body = _call(
        USER,
        "PUT",
        f"/properties/{pid}/usage",
        body={"tax_year": 2024, "fair_rental_days": days, "personal_use_days": 0},
    )
    _assert_clean_error(status, body)


def test_note_must_be_a_string(env, pid):  # noqa: F811
    status, body = _call(USER, "PUT", f"/properties/{pid}/notes", body={"text": 123})
    _assert_clean_error(status, body)
    assert body["field"] == "text"


def test_carryforward_fully_allowed_must_be_boolean(env):  # noqa: F811
    """``bool("false")`` is True, so a string used to silently flip the flag."""
    status, body = _call(
        USER, "PUT", "/carryforward/years/2024", body={"fully_allowed": "false"}
    )
    _assert_clean_error(status, body)
    assert body["field"] == "fully_allowed"


# --- Size limits and structure --------------------------------------------------


def test_oversized_string_is_rejected(env, pid):  # noqa: F811
    status, body = _call(USER, "PUT", f"/properties/{pid}/notes", body={"text": BIG})
    _assert_clean_error(status, body)


def test_oversized_list_is_rejected(env):  # noqa: F811
    status, body = _call(
        USER, "POST", "/imports/schedule-e", body={"tax_year": 2024, "entries": [{}] * 1001}
    )
    _assert_clean_error(status, body)


def test_deeply_nested_json_is_rejected(env):  # noqa: F811
    nested: object = "x"
    for _ in range(50):
        nested = {"a": nested}
    status, body = _call(USER, "POST", "/properties", body=nested)
    _assert_clean_error(status, body)


def test_pathological_json_nesting_does_not_500(env):  # noqa: F811
    event = {
        "requestContext": {
            "http": {"method": "POST", "path": "/properties"},
            "authorizer": {"jwt": {"claims": {"sub": USER}}},
        },
        "body": "[" * 100_000,
    }
    from logstead.router.handler import handler

    resp = handler(event)
    assert resp["statusCode"] == 400


def test_combined_report_property_ids_are_bounded_and_validated(env):  # noqa: F811
    status, body = _call(
        USER,
        "GET",
        "/reports/combined",
        query={"taxYear": 2024, "propertyIds": ",".join(["a"] * 101)},
    )
    _assert_clean_error(status, body)
    status, body = _call(
        USER, "GET", "/reports/combined", query={"taxYear": 2024, "propertyIds": "a#b"}
    )
    _assert_clean_error(status, body)


# --- Path ids -------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/properties/" + "a" * 129,
        "/properties/a#b",
        "/properties/a%23b",
        "/businesses/" + "a" * 3000,
        "/imports/" + "a" * 3000 + "/drafts",
        "/imports/schedule-e/extractions/a b",
    ],
)
def test_malformed_path_ids_get_the_not_found_response(env, path):  # noqa: F811
    status, body = _call(USER, "GET", path)
    _assert_clean_error(status, body, expected=404)


# --- Error responses do not leak internals ---------------------------------------


def test_unhandled_exception_returns_generic_500(env, monkeypatch):  # noqa: F811
    from logstead.router import handler as handler_module

    def boom(*_a, **_k):
        raise RuntimeError("secret table Logstead arn:aws:dynamodb:us-east-1:123:table/Logstead")

    monkeypatch.setattr(handler_module, "_list_properties", boom)
    monkeypatch.setattr(
        handler_module,
        "_ROUTES",
        tuple(
            (m, t, boom if t == "/properties" and m == "GET" else h, p)
            for m, t, h, p in handler_module._ROUTES
        ),
    )
    status, body = _call(USER, "GET", "/properties")
    assert status == 500
    assert body == {"error": "internal", "message": "An unexpected error occurred."}


def test_restore_write_failure_does_not_leak_the_cause(env, monkeypatch):  # noqa: F811
    """The restore conflict message used to embed ``str(exc)`` (boto text)."""
    from logstead.repository.dynamo_repo import DynamoRepository

    status, doc = _call(USER, "GET", "/backup")
    assert status == 200

    def boom(self, *_a, **_k):
        raise RuntimeError("ResourceNotFoundException: table Logstead-prod-secret")

    monkeypatch.setattr(DynamoRepository, "transact_write", boom)
    _call(USER, "POST", "/properties", body={
        "name": "P", "address_text": "1 Main St", "property_type": "single_family"})
    status, doc = _call(USER, "GET", "/backup")
    status, body = _call(USER, "POST", "/backup/restore", body=doc)
    if status == 409:
        assert "Logstead-prod-secret" not in json.dumps(body)
