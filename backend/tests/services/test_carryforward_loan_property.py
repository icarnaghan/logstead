"""Property-based test for loan interest in the carryforward.

* Property 19 (loan-balance-anchor): Data years and carryforward net include
  override-only years. Every tax year at or before the latest completed tax
  year in which an included Loan has a generated or override-only rollup
  appears among the Data_Years even with no transactions or depreciation, the
  earliest data year of a property is at most the smallest of its loans'
  anchor years and override years, and the Schedule_E_Net the carryforward
  uses for a year equals the sum over properties of ``report_for(...).totals.net``
  (which includes override-only interest).

Also covers: a service wired with ``loans=None`` behaves as before.

**Validates: Requirements 7.4, 7.5, 7.6**
"""

from __future__ import annotations

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
from logstead.services.carryforward import CarryforwardService
from logstead.services.dashboard import earliest_data_year, latest_tax_year
from logstead.services.depreciation import DepreciationService
from logstead.services.loan import (
    LoanService,
    build_yearly_rollups,
    compute_payment_rows,
    monthly_interest,
    override_year_allowed,
)
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

REGION = "us-east-1"
TABLE_NAME = "logstead-cf-loan-test"
BUCKET = "logstead-cf-loan-files"
USER = "user-cf-loan"
_MAX_EXAMPLES = 20
ZERO = Decimal("0.00")

MORTGAGE_CAT = "mortgage-interest-banks"  # Line 12
OTHER_EXPENSE_CAT = "other-interest"  # Line 13


class Env:
    def __init__(self, ddb: Any, s3: Any) -> None:
        self.ddb = ddb
        self.repo = DynamoRepository(ddb, TABLE_NAME)
        files = S3FileAdapter(s3, BUCKET)
        self.properties = PropertyService(self.repo, USER)
        self.transactions = TransactionService(self.repo, files)
        self.depreciation = DepreciationService(self.repo)
        self.loans = LoanService(self.repo)
        self.reports = ReportingService(
            self.transactions, self.depreciation, self.properties, loans=self.loans
        )
        self.reports_plain = ReportingService(
            self.transactions, self.depreciation, self.properties, loans=None
        )
        self.cf = CarryforwardService(
            self.repo,
            USER,
            self.reports,
            self.properties,
            self.transactions,
            self.depreciation,
            self.loans,
        )
        self.cf_plain = CarryforwardService(
            self.repo,
            USER,
            self.reports_plain,
            self.properties,
            self.transactions,
            self.depreciation,
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

_LATEST = latest_tax_year()

# Anchor-shape loans. Anchor dates reach past the latest completed tax year;
# overrides may land on pre-anchor years (before any transaction) or the anchor
# year, including 0.00.
_loan_spec = st.tuples(
    st.integers(100_000, 50_000_000).map(_money),  # anchor balance
    st.integers(0, 120_000).map(lambda n: Decimal(n).scaleb(-4)),  # rate % (may be 0)
    st.integers(100, 5_000),  # principal share of balance in the payment (bps)
    st.dates(date(2016, 1, 1), date(_LATEST + 1, 12, 31)),  # anchor date
    st.booleans(),  # include_in_report
    st.lists(
        st.tuples(st.integers(1990, _LATEST + 1), st.integers(0, 5_000_000).map(_money)),
        max_size=3,
    ),  # override attempts (year, amount); disallowed years are skipped
)
_amounts = st.integers(1, 5_000_000).map(_money)
# (year, kind, amount): transactions across years, some past the cap.
_txn_spec = st.tuples(
    st.integers(2016, _LATEST + 2),
    st.sampled_from(["line12", "other", "income"]),
    _amounts,
)
_property_spec = st.fixed_dictionaries(
    {
        "loans": st.lists(_loan_spec, max_size=2),
        "txns": st.lists(_txn_spec, max_size=4),
    }
)
_property_specs = st.lists(_property_spec, min_size=1, max_size=2)


# ---------------------------------------------------------------------------
# Builders / expectations
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


def _engine_interest_by_year(view: LoanView) -> dict[int, Decimal]:
    """Independent expectation from the pure engine (not the storage reader)."""
    loan = _loan_of(view)
    rows, _ = compute_payment_rows(loan)
    return {r.tax_year: r.effective_interest for r in build_yearly_rollups(loan, rows)}


def _build_property(env: Env, spec: dict) -> tuple[str, list[LoanView]]:
    pid = _ok(
        env.properties.create(
            PropertyInput(
                name="Carryforward Loan Subject",
                address_text="25 Carry Way",
                property_type="single_family",
            )
        )
    ).id
    _USED_PIDS.append(pid)
    cats = {
        "line12": ("expense", MORTGAGE_CAT),
        "other": ("expense", OTHER_EXPENSE_CAT),
        "income": ("income", "rents-received"),
    }
    for n, (year, kind, amount) in enumerate(spec["txns"]):
        txn_type, cat = cats[kind]
        _ok(
            env.transactions.create(
                TransactionInput(
                    property_id=pid,
                    date=date(year, 1 + (n % 12), 1 + (n % 27)).isoformat(),
                    amount=amount,
                    type=txn_type,
                    category_id=cat,
                    description=None,
                )
            )
        )
    views = []
    for balance, rate, share_bps, anchor, include, overrides in spec["loans"]:
        share = max(Decimal("0.01"), (balance * share_bps / 10_000).quantize(Decimal("0.01")))
        view = _ok(
            env.loans.create_loan(
                LoanInput(
                    property_id=pid,
                    description="Carryforward loan",
                    annual_interest_rate=rate,
                    monthly_payment=monthly_interest(balance, rate) + share,
                    anchor_balance=balance,
                    anchor_date=anchor.isoformat(),
                    extra_principal=ZERO,
                    payoff_date=None,
                    include_in_report=include,
                )
            )
        )
        for year, amount in overrides:
            loan = _loan_of(view)
            generated = {
                r.tax_year
                for r in build_yearly_rollups(loan, compute_payment_rows(loan)[0])
            }
            if override_year_allowed(year, int(view.anchor_date[:4]), generated):
                _ok(env.loans.set_interest_override(pid, view.id, year, amount))
                view = _ok(env.loans.get_loan(pid, view.id))
        views.append(view)
    return pid, views


def _expected_net(
    env: Env, pid: str, spec: dict, views: list[LoanView], year: int
) -> Decimal:
    """Independent net: manual-only net, with Line 12 swapped for loan interest."""
    plain = _ok(env.reports_plain.report_for(pid, year)).totals.net
    manual12 = sum(
        (a for y, k, a in spec["txns"] if y == year and k == "line12"), ZERO
    )
    loan_total = sum(
        (
            _engine_interest_by_year(v).get(year, ZERO)
            for v in views
            if v.include_in_report
        ),
        ZERO,
    )
    if loan_total > ZERO:
        return plain + manual12 - loan_total
    return plain


# ---------------------------------------------------------------------------
# Property 19
# ---------------------------------------------------------------------------


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(specs=_property_specs)
def test_carryforward_sees_loan_interest(env: Env, specs: list[dict]) -> None:
    """Property 19: override-only years are Data_Years and feed the net."""
    _purge(env)
    built = [_build_property(env, s) for s in specs]

    txn_years: set[int] = set()
    loan_years: set[int] = set()
    for spec, (_, views) in zip(specs, built, strict=True):
        txn_years |= {y for y, _, _ in spec["txns"]}
        for v in views:
            if v.include_in_report:
                loan_years |= set(_engine_interest_by_year(v))
    expected_years = sorted(y for y in txn_years | loan_years if y <= _LATEST)

    # The earliest data year is at most each loan's anchor and override years.
    for pid, views in built:
        earliest = earliest_data_year(pid, env.transactions, env.depreciation, env.loans)
        for v in views:
            assert earliest is not None
            assert earliest <= int(v.anchor_date[:4])
            assert all(earliest <= int(y) for y in v.interest_overrides)

    summary = env.cf.reconcile()
    assert [y.tax_year for y in summary.years] == expected_years
    assert all(y <= _LATEST for y in (r.tax_year for r in summary.years))

    # Every capped included-loan year appears, even with no txns/depreciation.
    for year in loan_years:
        if year <= _LATEST:
            assert year in expected_years

    for row in summary.years:
        # Equals the sum of report_for(...).totals.net across properties.
        sum_reports = sum(
            (
                _ok(env.reports.report_for(pid, row.tax_year)).totals.net
                for pid, _ in built
            ),
            ZERO,
        )
        assert row.schedule_e_net == sum_reports
        # ...and reflects loan-generated Line 12 per the pure engine.
        sum_expected = sum(
            (
                _expected_net(env, pid, spec, views, row.tax_year)
                for spec, (pid, views) in zip(specs, built, strict=True)
            ),
            ZERO,
        )
        assert row.schedule_e_net == sum_expected

    # Behavior unchanged with loans=None: manual-only years and nets.
    plain = env.cf_plain.reconcile()
    assert [y.tax_year for y in plain.years] == sorted(
        y for y in txn_years if y <= _LATEST
    )
    for row in plain.years:
        assert row.schedule_e_net == sum(
            (
                _ok(env.reports_plain.report_for(pid, row.tax_year)).totals.net
                for pid, _ in built
            ),
            ZERO,
        )
