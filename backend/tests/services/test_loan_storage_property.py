"""Property-based tests for loan storage (loan-balance-anchor design).

* Property 11: Stored rollups always equal the engine output, with none stale.
* Property 13 (task 3.7, added to this file later): Delete and list are exact
  and scoped. Shared fixtures and helpers below are written for reuse by it.

**Validates: Requirements 1.1, 1.9, 5.6, 12.2**
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import boto3
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.depreciation import AssetInput
from logstead.services.depreciation import DepreciationService
from logstead.models.loan import Loan, LoanInput, LoanView
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.loan import (
    LoanService,
    _rollup_from_item,
    build_yearly_rollups,
    compute_payment_rows,
    override_year_allowed,
)

REGION = "us-east-1"
TABLE_NAME = "logstead-loan-storage-test"
_MAX_EXAMPLES = 25


# ---------------------------------------------------------------------------
# Fixtures and helpers (shared with later properties in this file)
# ---------------------------------------------------------------------------


class Env:
    def __init__(self, ddb: Any) -> None:
        self.ddb = ddb
        self.repo = DynamoRepository(ddb, TABLE_NAME)
        self.loans = LoanService(self.repo)


@pytest.fixture(scope="module")
def env():
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
                    "IndexName": name,
                    "KeySchema": [
                        {"AttributeName": f"{name}PK", "KeyType": "HASH"},
                        {"AttributeName": f"{name}SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
                for name in ("GSI1", "GSI2")
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield Env(ddb)


_USED_PIDS: list[str] = []


def _purge(env: Env) -> None:
    """Drop every item written by earlier examples."""
    while _USED_PIDS:
        pk = keys.property_scoped_pk(_USED_PIDS.pop())
        kwargs: dict[str, Any] = {
            "TableName": TABLE_NAME,
            "KeyConditionExpression": "PK = :pk",
            "ExpressionAttributeValues": {":pk": {"S": pk}},
            "ProjectionExpression": "PK, SK",
        }
        while True:
            page = env.ddb.query(**kwargs)
            for item in page["Items"]:
                env.ddb.delete_item(TableName=TABLE_NAME, Key=item)
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _new_property_id() -> str:
    pid = f"prop-{uuid.uuid4().hex[:12]}"
    _USED_PIDS.append(pid)
    return pid


def _money(cents: int) -> Decimal:
    return Decimal(cents).scaleb(-2).quantize(Decimal("0.01"))


def _ok(result: Any) -> Any:
    assert result.error is None, result.error
    return result.value


@dataclass(frozen=True)
class Params:
    """Valid-by-construction anchor-shape loan parameters."""

    balance: Decimal
    rate: Decimal
    payment: Decimal
    anchor: date
    payoff: date | None
    include: bool


def _loan_input(property_id: str, p: Params) -> LoanInput:
    return LoanInput(
        property_id=property_id,
        description="Storage loan",
        annual_interest_rate=p.rate,
        monthly_payment=p.payment,
        anchor_balance=p.balance,
        anchor_date=p.anchor.isoformat(),
        extra_principal=Decimal("0.00"),
        payoff_date=p.payoff.isoformat() if p.payoff else None,
        include_in_report=p.include,
    )


def _raw_rollups(env: Env, property_id: str, loan_id: str) -> list[dict[str, Any]]:
    items = env.repo.query(
        keys.property_scoped_pk(property_id),
        sk_begins_with=keys.loan_year_list_prefix(loan_id),
        money_attrs=set(),
    )
    return sorted(items, key=lambda i: i["SK"])


def _loan_of(view: LoanView) -> Loan:
    return Loan(
        id=view.id,
        property_id=view.property_id,
        description=view.description,
        annual_interest_rate=view.annual_interest_rate,
        monthly_payment=view.monthly_payment,
        anchor_balance=view.anchor_balance,
        anchor_date=view.anchor_date,
        extra_principal=view.extra_principal,
        payoff_date=view.payoff_date,
        original_principal=view.original_principal,
        closing_date=view.closing_date,
        include_in_report=view.include_in_report,
        interest_overrides={int(y): v for y, v in view.interest_overrides.items()},
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _engine_rollups(view: LoanView):
    loan = _loan_of(view)
    rows, _ = compute_payment_rows(loan)
    return build_yearly_rollups(loan, rows)


def _assert_rollups_match_engine(env: Env, view: LoanView) -> None:
    """Stored rows are exactly the engine rollups, with the right keys."""
    expected = sorted(
        _engine_rollups(view),
        key=lambda r: keys.loan_year_sk(r.loan_id, r.tax_year),
    )
    raw = _raw_rollups(env, view.property_id, view.id)
    assert len(raw) == len(expected)  # no stale or duplicate rows
    assert [_rollup_from_item(i) for i in raw] == expected
    for item in raw:
        year = int(item["taxYear"])
        assert item["PK"] == f"PROPERTY#{view.property_id}"
        assert item["SK"] == f"LOAN#{view.id}#YEAR#{year}"
        assert item["GSI2PK"] == f"PROPERTY#{view.property_id}#YEAR#{year}"
        assert item["GSI2SK"] == f"LOANYR#{view.id}"
    loan_item = env.repo.get_item(
        keys.property_scoped_pk(view.property_id),
        keys.loan_sk(view.id),
        money_attrs=set(),
    )
    assert loan_item is not None
    assert loan_item["SK"] == f"LOAN#{view.id}"
    assert "GSI1PK" not in loan_item and "GSI2PK" not in loan_item


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def _params(draw) -> Params:
    balance_cents = draw(st.integers(100_000, 50_000_000))
    rate = Decimal(draw(st.integers(0, 120_000))).scaleb(-4)
    balance = _money(balance_cents)
    # Payment exceeds first-month interest and pays off within ~240 rows,
    # keeping one write well under the 100-action transaction cap.
    first_interest = int(
        (Decimal(balance_cents) * rate / 1200).to_integral_value()
    )
    # Principal per row starts at >= balance/240 and never shrinks.
    floor = first_interest + balance_cents // 240 + 1
    payment = _money(floor + draw(st.integers(0, 200_000)))
    anchor = draw(st.dates(date(1995, 1, 1), date(2040, 12, 31)))
    payoff = (
        anchor + timedelta(days=draw(st.integers(40, 3000)))
        if draw(st.booleans())
        else None
    )
    return Params(balance, rate, payment, anchor, payoff, draw(st.booleans()))


_overrides = st.integers(0, 10_000_000).map(_money)

# Operations: ("update", Params) | ("set", year-pick, amount) | ("clear", pick)
_ops = st.one_of(
    st.tuples(st.just("update"), _params()),
    st.tuples(st.just("set"), st.integers(0, 10_000), _overrides),
    st.tuples(st.just("clear"), st.integers(0, 10_000)),
)


# ---------------------------------------------------------------------------
# Property 11
# ---------------------------------------------------------------------------


@settings(
    deadline=None,
    max_examples=_MAX_EXAMPLES,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    first=_params(),
    ops=st.lists(_ops, min_size=1, max_size=6),
    others=st.lists(_params(), max_size=2),
)
def test_stored_rollups_always_equal_engine_output_with_none_stale(
    env: Env, first: Params, ops: list[tuple], others: list[Params]
) -> None:
    """Feature: loan-balance-anchor, Property 11: Stored rollups always equal
    the engine output, with none stale.

    **Validates: Requirements 1.1, 1.9, 5.6, 12.2**
    """
    _purge(env)
    pid = _new_property_id()

    view: LoanView = _ok(env.loans.create_loan(_loan_input(pid, first)))
    _assert_rollups_match_engine(env, view)

    for op in ops:
        if op[0] == "update":
            updated = _ok(env.loans.update_loan(pid, view.id, _loan_input(pid, op[1])))
            assert updated.id == view.id
            assert updated.created_at == view.created_at
            # Every retained override is still allowed by the new schedule.
            loan = _loan_of(updated)
            rows, _ = compute_payment_rows(loan)
            generated = {int(r.date[:4]) for r in rows}
            anchor_year = int(loan.anchor_date[:4])
            assert all(
                override_year_allowed(y, anchor_year, generated)
                for y in loan.interest_overrides
            )
            view = updated
        elif op[0] == "set":
            loan = _loan_of(view)
            rows, _ = compute_payment_rows(loan)
            anchor_year = int(loan.anchor_date[:4])
            allowed = sorted(
                {int(r.date[:4]) for r in rows}
                | set(range(max(1900, anchor_year - 5), anchor_year + 1))
            )
            year = allowed[op[1] % len(allowed)]
            _ok(env.loans.set_interest_override(pid, view.id, year, op[2]))
            view = _ok(env.loans.get_loan(pid, view.id))
            assert view.interest_overrides[str(year)] == op[2]
        else:
            current = sorted(view.interest_overrides)
            if current:
                year = int(current[op[1] % len(current)])
            else:
                year = int(view.anchor_date[:4])  # clearing a missing override
            _ok(env.loans.clear_interest_override(pid, view.id, year))
            view = _ok(env.loans.get_loan(pid, view.id))
            assert str(year) not in view.interest_overrides
        _assert_rollups_match_engine(env, view)

    views = [view]
    for p in others:
        extra = _ok(env.loans.create_loan(_loan_input(pid, p)))
        _assert_rollups_match_engine(env, extra)
        views.append(extra)
    # Creating others never disturbed the first loan's rows.
    _assert_rollups_match_engine(env, views[0])

    # One GSI2 query per year equals the sum of the engine's Effective_Interest
    # over the included loans.
    all_years = {r.tax_year for v in views for r in _engine_rollups(v)}
    for year in range(min(all_years) - 1, max(all_years) + 2):
        expected = sum(
            (
                r.effective_interest
                for v in views
                if v.include_in_report
                for r in _engine_rollups(v)
                if r.tax_year == year
            ),
            Decimal("0.00"),
        )
        got = env.loans.property_effective_interest_for_year(pid, year)
        assert got == expected
        assert got.as_tuple().exponent == -2


# ---------------------------------------------------------------------------
# Property 13
# ---------------------------------------------------------------------------


def _snapshot(env: Env, property_id: str) -> dict[str, dict[str, Any]]:
    """Every raw item in a property partition, keyed by sort key."""
    items = env.repo.query(
        keys.property_scoped_pk(property_id), money_attrs=set()
    )
    return {i["SK"]: i for i in items}


def _asset_input(property_id: str, cost_cents: int) -> AssetInput:
    return AssetInput(
        property_id=property_id,
        description="Storage asset",
        cost_basis=_money(cost_cents),
        placed_in_service_date="2020-03-15",
    )


@settings(
    deadline=None,
    max_examples=_MAX_EXAMPLES,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    loan_params=st.lists(
        st.lists(_params(), min_size=0, max_size=3), min_size=1, max_size=3
    ),
    asset_counts=st.lists(st.integers(0, 2), min_size=3, max_size=3),
    pick=st.integers(0, 1000),
    override_only=st.booleans(),
    override_amount=_overrides,
)
def test_delete_and_list_are_exact_and_scoped(
    env: Env,
    loan_params: list[list[Params]],
    asset_counts: list[int],
    pick: int,
    override_only: bool,
    override_amount: Decimal,
) -> None:
    """Feature: loan-balance-anchor, Property 13: Delete and list are exact
    and scoped.

    **Validates: Requirements 1.10, 13.4**
    """
    assume(any(loan_params))  # something to delete

    _purge(env)
    depreciation = DepreciationService(env.repo)

    pids = [_new_property_id() for _ in loan_params]
    views: dict[str, list[LoanView]] = {}
    asset_ids: dict[str, set[str]] = {}
    for idx, (pid, group) in enumerate(zip(pids, loan_params)):
        views[pid] = [_ok(env.loans.create_loan(_loan_input(pid, p))) for p in group]
        assets = [
            _ok(depreciation.create_asset(_asset_input(pid, 10_000_00 + n)))
            for n in range(asset_counts[idx])
        ]
        asset_ids[pid] = {a.id for a in assets}

    all_loans = [(pid, v) for pid in pids for v in views[pid]]
    target_pid, target = all_loans[pick % len(all_loans)]

    if override_only:
        # An override on a year without a generated row yields an
        # override-only rollup row; it must be deleted with the loan too.
        year = int(target.anchor_date[:4]) - 1
        _ok(env.loans.set_interest_override(target_pid, target.id, year, override_amount))

    before = {pid: _snapshot(env, pid) for pid in pids}
    target_prefix = keys.loan_sk(target.id)
    own_keys = {
        sk
        for sk in before[target_pid]
        if sk == target_prefix or sk.startswith(f"{target_prefix}#YEAR#")
    }
    assert target_prefix in own_keys

    _ok(env.loans.delete_loan(target_pid, target.id))

    # The loan item and every rollup row (override-only included) are gone,
    # and every other row, in every property, is unchanged.
    after = {pid: _snapshot(env, pid) for pid in pids}
    expected_target = {
        sk: item for sk, item in before[target_pid].items() if sk not in own_keys
    }
    assert after[target_pid] == expected_target
    for pid in pids:
        if pid != target_pid:
            assert after[pid] == before[pid]
    assert env.loans.get_loan(target_pid, target.id).error is not None

    # Listing loans returns exactly that property's remaining loans and no
    # rollup rows.
    for pid in pids:
        listed = _ok(env.loans.list_loans(pid))
        expected_ids = {
            v.id
            for v in views[pid]
            if not (pid == target_pid and v.id == target.id)
        }
        assert len(listed) == len(expected_ids)
        assert {v.id for v in listed} == expected_ids
        assert all(v.property_id == pid for v in listed)

        # Listing assets returns only that property's assets: no loan or
        # rollup rows.
        assets = depreciation.list_assets(pid)
        assert {a.id for a in assets} == asset_ids[pid]
        assert all(a.property_id == pid for a in assets)
