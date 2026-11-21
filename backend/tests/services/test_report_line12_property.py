"""Property-based tests for Line 12 in the Schedule E report (design Properties 20-23).

* Property 18 (loan-balance-anchor): Line 12 uses loan interest or manual
  interest, never both, including override-only years (anchor-shape loans,
  pre-anchor and anchor-year overrides, including 0.00).
  **Validates: Requirements 7.1, 7.2**
* Property 20: Line 12 uses loan interest or manual interest, never both.
* Property 21: Totals include Line 12 and Line 13 is untouched.
* Property 22: Combined report columns follow the same rules; portfolio sums them.
* Property 23: Reports are reproducible.

Also covers: Loans with Report_Inclusion off are ignored, and a service built
with ``loans=None`` behaves exactly like the manual-only report.

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.12, 6.13, 7.5**
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.loan import Loan, LoanInput, LoanView
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.depreciation import DepreciationService
from logstead.services.loan import (
    LoanService,
    build_yearly_rollups,
    compute_payment_rows,
    monthly_interest,
    override_year_allowed,
)
from logstead.services.property import PropertyService
from logstead.services.report import MORTGAGE_INTEREST_LINE, ReportingService
from logstead.services.transaction import TransactionService

REGION = "us-east-1"
TABLE_NAME = "logstead-line12-test"
BUCKET = "logstead-line12-files"
USER = "user-line12"
TAX_YEAR = 2024
_MAX_EXAMPLES = 20
ZERO = Decimal("0.00")

MORTGAGE_CAT = "mortgage-interest-banks"  # Line 12
OTHER_INTEREST_CAT = "other-interest"  # Line 13


class Env:
    def __init__(self, ddb: Any, s3: Any) -> None:
        self.ddb = ddb
        self.repo = DynamoRepository(ddb, TABLE_NAME)
        files = S3FileAdapter(s3, BUCKET)
        self.properties = PropertyService(self.repo, USER)
        self.transactions = TransactionService(self.repo, files)
        self.depreciation = DepreciationService(self.repo)
        self.loans = LoanService(self.repo)
        self.report = ReportingService(
            self.transactions, self.depreciation, self.properties, loans=self.loans
        )
        self.report_no_loans = ReportingService(
            self.transactions, self.depreciation, self.properties, loans=None
        )


@pytest.fixture(scope="module")
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
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        yield Env(ddb, s3)


_USED_PIDS: list[str] = []


def _delete_partition(env: Env, pk: str) -> None:
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


def _purge(env: Env) -> None:
    """Drop everything written by earlier examples so the table stays small."""
    while _USED_PIDS:
        _delete_partition(env, keys.property_scoped_pk(_USED_PIDS.pop()))
    _delete_partition(env, keys.user_pk(USER))


def _ok(result: Any) -> Any:
    assert result.error is None, result.error
    return result.value


def _money(cents: int) -> Decimal:
    return Decimal(cents).scaleb(-2).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Anchor-shape loans. Anchor dates run from 2022 through 2026 so TAX_YEAR is
# sometimes a generated year, sometimes the anchor year (partial interest or
# override-only) and sometimes before the anchor (override-only).
_loan_spec = st.tuples(
    st.integers(100_000, 50_000_000).map(_money),  # anchor balance
    st.integers(0, 120_000).map(lambda n: Decimal(n).scaleb(-4)),  # rate % (may be 0)
    st.integers(100, 5_000),  # principal share of balance in the payment (bps)
    st.dates(date(2022, 1, 1), date(2026, 12, 31)),  # anchor date
    st.booleans(),  # include_in_report
    st.one_of(st.none(), st.integers(0, 5_000_000).map(_money)),  # override (maybe 0)
)
_amounts = st.integers(1, 5_000_000).map(_money)
_property_spec = st.fixed_dictionaries(
    {
        "loans": st.lists(_loan_spec, max_size=3),
        "line12": st.lists(_amounts, max_size=5),
        "line12_other_year": st.lists(_amounts, max_size=2),
        "line13": st.lists(_amounts, max_size=3),
        "income": st.lists(_amounts, max_size=2),
    }
)
_property_specs = st.lists(_property_spec, min_size=1, max_size=3)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


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
        original_principal=view.original_principal,
        closing_date=view.closing_date,
        payoff_date=view.payoff_date,
        include_in_report=view.include_in_report,
        interest_overrides={int(y): v for y, v in view.interest_overrides.items()},
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _effective_interest(view: LoanView, year: int) -> Decimal:
    """Independent expectation from the pure engine (not the storage reader)."""
    loan = _loan_of(view)
    rows, _ = compute_payment_rows(loan)
    return sum(
        (r.effective_interest for r in build_yearly_rollups(loan, rows) if r.tax_year == year),
        ZERO,
    )


def _add_loan(env: Env, pid: str, spec: tuple) -> LoanView:
    balance, rate, share_bps, anchor, include, override = spec
    # Payment exceeds first-month interest and keeps the schedule under the cap.
    share = max(Decimal("0.01"), (balance * share_bps / 10_000).quantize(Decimal("0.01")))
    payment = monthly_interest(balance, rate) + share
    view = _ok(
        env.loans.create_loan(
            LoanInput(
                property_id=pid,
                description="Line 12 loan",
                annual_interest_rate=rate,
                monthly_payment=payment,
                anchor_balance=balance,
                anchor_date=anchor.isoformat(),
                extra_principal=ZERO,
                payoff_date=None,
                include_in_report=include,
            )
        )
    )
    loan = _loan_of(view)
    generated = {r.tax_year for r in build_yearly_rollups(loan, compute_payment_rows(loan)[0])}
    allowed = override_year_allowed(TAX_YEAR, int(view.anchor_date[:4]), generated)
    if override is not None and allowed:
        _ok(env.loans.set_interest_override(pid, view.id, TAX_YEAR, override))
        view = _ok(env.loans.get_loan(pid, view.id))
    return view


def _add_txn(env: Env, pid: str, kind: str, cat: str, amount: Decimal, year: int, n: int) -> None:
    _ok(
        env.transactions.create(
            TransactionInput(
                property_id=pid,
                date=date(year, 1 + (n % 12), 1 + (n % 27)).isoformat(),
                amount=amount,
                type=kind,
                category_id=cat,
                description=None,
            )
        )
    )


def _build_property(env: Env, spec: dict) -> tuple[str, list[LoanView]]:
    pid = _ok(
        env.properties.create(
            PropertyInput(
                name="Line 12 Subject",
                address_text="12 Interest Way",
                property_type="single_family",
            )
        )
    ).id
    _USED_PIDS.append(pid)
    n = 0
    for amount in spec["line12"]:
        _add_txn(env, pid, "expense", MORTGAGE_CAT, amount, TAX_YEAR, n)
        n += 1
    for amount in spec["line12_other_year"]:
        _add_txn(env, pid, "expense", MORTGAGE_CAT, amount, TAX_YEAR - 1, n)
        n += 1
    for amount in spec["line13"]:
        _add_txn(env, pid, "expense", OTHER_INTEREST_CAT, amount, TAX_YEAR, n)
        n += 1
    for amount in spec["income"]:
        _add_txn(env, pid, "income", "rents-received", amount, TAX_YEAR, n)
        n += 1
    views = [_add_loan(env, pid, ls) for ls in spec["loans"]]
    return pid, views


def _sum(values: Any) -> Decimal:
    return sum(values, ZERO)


def _check_property(env: Env, pid: str, spec: dict, views: list[LoanView]) -> Any:
    """Assert Properties 20, 21 (and 23) for one property; return its report."""
    manual = _sum(spec["line12"])
    manual_count = len(spec["line12"])
    loan_total = _sum(
        _effective_interest(v, TAX_YEAR) for v in views if v.include_in_report
    )

    rpt = _ok(env.report.report_for(pid, TAX_YEAR))
    line12 = rpt.line(MORTGAGE_INTEREST_LINE)
    assert line12 is not None

    # Property 20
    if loan_total > ZERO:
        assert line12.total == loan_total
        assert rpt.line12.source == "loan-generated"
        assert rpt.line12.superseded_manual_interest.amount == manual
        assert rpt.line12.superseded_manual_interest.count == manual_count
    else:
        assert line12.total == manual
        assert rpt.line12.source == "transaction-entered"
        assert rpt.line12.superseded_manual_interest.amount == ZERO
        assert rpt.line12.superseded_manual_interest.count == 0
    if loan_total > ZERO and manual > ZERO:
        assert line12.total != loan_total + manual

    # Property 21
    line13 = rpt.line(13)
    assert line13 is not None and line13.total == _sum(spec["line13"])
    assert rpt.totals.total_income == _sum(spec["income"])
    expense_sum = _sum(ln.total for ln in rpt.lines if ln.kind == "expense")
    assert rpt.totals.total_expenses == expense_sum
    assert rpt.totals.net == rpt.totals.total_income - rpt.totals.total_expenses

    # Property 23
    assert _ok(env.report.report_for(pid, TAX_YEAR)) == rpt

    # loans=None: manual-only report, unchanged behavior.
    plain = _ok(env.report_no_loans.report_for(pid, TAX_YEAR))
    assert plain.line(MORTGAGE_INTEREST_LINE).total == manual
    assert plain.line12.source == "transaction-entered"
    assert plain.line12.superseded_manual_interest.amount == ZERO
    assert plain.line12.superseded_manual_interest.count == 0
    return rpt


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(spec=_property_spec)
def test_line12_precedence_totals_and_line13(env: Env, spec: dict) -> None:
    """Properties 20, 21, 23 for a single property."""
    _purge(env)
    pid, views = _build_property(env, spec)
    _check_property(env, pid, spec, views)


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(spec=_property_spec, excluded=st.lists(_loan_spec, min_size=1, max_size=2))
def test_excluded_loans_have_no_effect(env: Env, spec: dict, excluded: list[tuple]) -> None:
    """Report_Inclusion off: adding such loans changes no report output."""
    _purge(env)
    pid, _ = _build_property(env, spec)
    before = _ok(env.report.report_for(pid, TAX_YEAR))
    for ls in excluded:
        _add_loan(env, pid, (*ls[:4], False, ls[5]))
    assert _ok(env.report.report_for(pid, TAX_YEAR)) == before


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(specs=_property_specs)
def test_combined_report_columns_and_portfolio_sums(env: Env, specs: list[dict]) -> None:
    """Properties 22 and 23."""
    _purge(env)
    built = [_build_property(env, s) for s in specs]
    pids = [pid for pid, _ in built]

    combined = _ok(env.report.combined_report(pids, TAX_YEAR))
    assert len(combined.properties) == len(pids)

    total = ZERO
    amount = ZERO
    count = 0
    for column, pid, (spec, (_, views)) in zip(
        combined.properties, pids, zip(specs, built), strict=True
    ):
        own = _check_property(env, pid, spec, views)
        assert column.line(MORTGAGE_INTEREST_LINE).total == own.line(MORTGAGE_INTEREST_LINE).total
        assert column.line12 == own.line12
        total += own.line(MORTGAGE_INTEREST_LINE).total
        amount += own.line12.superseded_manual_interest.amount
        count += own.line12.superseded_manual_interest.count

    assert combined.line12.total == total
    assert combined.line12.superseded_manual_interest.amount == amount
    assert combined.line12.superseded_manual_interest.count == count
    assert combined.totals.net == combined.totals.total_income - combined.totals.total_expenses

    # Property 23 for the combined report.
    assert _ok(env.report.combined_report(pids, TAX_YEAR)) == combined
