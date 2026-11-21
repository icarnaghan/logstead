"""Checklist counts agree across the three routes, through the real router.

# Feature: year-end-checklist, Property 17: Counts agree across the three routes

**Validates: Requirements 15.5**

For generated stored data over one to three properties, the counts returned by
``GET /properties/{id}/checklist``, the matching year row of
``GET /properties/{id}/checklist/summary`` and the matching property row of
``GET /checklist/summary`` are identical.
"""
from __future__ import annotations

import json
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.loan import LoanInput
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.models.user import UserContext
from logstead.router import handler as handler_module
from logstead.router.handler import handler
from logstead.services.itemized import EntryInput, ItemizedExpenseService
from logstead.services.loan import LoanService
from logstead.services.property import PropertyService
from tests.services.test_imported_marker_update_property import USER_ID, _Env

YEAR = 2023
INCOME_CATS = ("rents-received", "royalties-received")
EXPENSE_CATS = ("insurance", "utilities", "advertising", "repairs")

_amount = st.integers(min_value=1, max_value=900_000).map(
    lambda cents: Decimal(cents) / Decimal(100)
)
_txn = st.tuples(
    st.sampled_from((YEAR, YEAR - 1)),
    st.sampled_from(INCOME_CATS + EXPENSE_CATS),
    _amount,
)
_property = st.fixed_dictionaries(
    {
        "txns": st.lists(_txn, max_size=4),
        "entries": st.lists(_amount, max_size=2),
        "loan": st.booleans(),
    }
)
_state = st.lists(_property, min_size=1, max_size=3)


def _call(method: str, path: str, query: dict[str, str] | None = None):
    event = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": {"sub": USER_ID}}},
        },
        "rawPath": path,
    }
    if query:
        event["queryStringParameters"] = query
    resp = handler(event)
    return resp["statusCode"], json.loads(resp["body"]) if resp["body"] else None


def _seed(env: _Env, index: int, spec) -> str:
    user = UserContext(user_id=USER_ID)
    created = PropertyService(env.repo, user).create(
        PropertyInput(name=f"Prop {index}", address_text=f"{index} Agree St")
    )
    assert created.is_ok, created.error
    pid = created.value.id
    for year, category, amount in spec["txns"]:
        kind = "income" if category in INCOME_CATS else "expense"
        made = env.txns.create(
            TransactionInput(
                property_id=pid,
                date=f"{year}-04-10",
                amount=amount,
                type=kind,
                category_id=category,
                description="x",
            )
        )
        assert made.is_ok, made.error
    itemized = ItemizedExpenseService(env.txns)
    for amount in spec["entries"]:
        made = itemized.create_entry(
            pid,
            "repairs",
            EntryInput(date=f"{YEAR}-05-05", amount=amount, description="e"),
        )
        assert made.is_ok, made.error
    if spec["loan"]:
        made = LoanService(env.repo).create_loan(
            LoanInput(
                property_id=pid,
                description="Mortgage",
                annual_interest_rate=Decimal("0.05"),
                monthly_payment=Decimal("1000.00"),
                anchor_balance=Decimal("100000.00"),
                anchor_date=f"{YEAR - 1}-12-31",
                original_principal=None,
                closing_date=None,
            )
        )
        assert made.is_ok, made.error
    return pid


def _check(state) -> None:
    env = _Env()
    handler_module.configure(repo=env.repo, files=env.files)
    try:
        pids = [_seed(env, i, spec) for i, spec in enumerate(state)]
        for year in (YEAR, YEAR - 1):
            status, portfolio = _call(
                "GET", "/checklist/summary", {"taxYear": str(year)}
            )
            assert status == 200, portfolio
            assert portfolio["tax_year"] == year
            rows = {row["property_id"]: row for row in portfolio["properties"]}
            for pid in pids:
                status, full = _call(
                    "GET",
                    f"/properties/{pid}/checklist",
                    {"taxYear": str(year)},
                )
                assert status == 200, full
                assert full["tax_year"] == year
                assert pid in rows
                assert rows[pid]["counts"] == full["counts"]

                status, summary = _call(
                    "GET", f"/properties/{pid}/checklist/summary"
                )
                assert status == 200, summary
                by_year = {y["tax_year"]: y["counts"] for y in summary["years"]}
                # Both years carry data only when a transaction exists in them.
                if year in by_year:
                    assert by_year[year] == full["counts"]
                counts = full["counts"]
                assert (
                    counts["done"]
                    + counts["needs_attention"]
                    + counts["not_applicable"]
                    == counts["total"]
                )
    finally:
        handler_module.reset_wiring()


@settings(max_examples=100, deadline=None)
@given(state=_state)
def test_counts_agree_across_the_three_routes(state):
    with mock_aws():
        _check(state)
