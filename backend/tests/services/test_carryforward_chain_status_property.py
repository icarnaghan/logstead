"""Property-based test: chain-aware status precedence is total and correct.

Feature: carryforward-chain-status, Property 1: Status follows the four-rule
precedence and is total.

*For any* Opening_Balance, per-year nets, allowed data (explicit amounts and
Fully_Allowed flags) and reported data (any subset of years reported), the
status of every year equals an independent oracle that works in integer cents
and applies the rules in order:

* ``unreported`` when there is no reported value;
* ``ok`` when reported (the Form 8582 carry-in) equals the expected carry-in;
* ``carried`` when the year is not the first, the prior year is reported, and
  reported equals the chain value (the PRIOR year's step, using its net and
  effective allowed, applied to the prior REPORTED carry-in);
* otherwise ``mismatch``.

The oracle does not call ``_apply_year_step`` or ``_effective_allowed``; it
re-derives the step from the nets, the allowed data this test set, and the
opening balance. Reported values are drawn from the oracle's expected, the
oracle's chain value, and off-by-one-cent variants of each, so every branch is
exercised.

Mirrors the moto-backed composition in ``test_carryforward_status_property.py``.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7**
"""

from __future__ import annotations

import contextlib
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.carryforward import STATUS_TOLERANCE, CarryforwardService
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"

_TAX_YEARS = [2018, 2019, 2020, 2022, 2023]
_CENTS = Decimal("0.01")


@contextlib.contextmanager
def _moto_service():
    """Isolated moto DynamoDB (base + GSI1 + GSI2) and S3, composed service."""
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
        properties = PropertyService(repo, USER)
        transactions = TransactionService(repo, S3FileAdapter(s3, BUCKET))
        depreciation = DepreciationService(repo)
        reports = ReportingService(transactions, depreciation, properties)
        service = CarryforwardService(
            repo, USER, reports, properties, transactions, depreciation
        )
        yield service, properties, transactions


# --- Strategies ---------------------------------------------------------------

_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_opening = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("50000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_INCOME_SPECS = [("income", "rents-received"), ("income", "royalties-received")]
_EXPENSE_SPECS = [("expense", "repairs"), ("expense", "utilities")]


@st.composite
def _txn(draw: st.DrawFn) -> tuple[str, str, Decimal, int]:
    ttype, category = draw(st.sampled_from(_INCOME_SPECS + _EXPENSE_SPECS))
    return (
        ttype,
        category,
        draw(_amounts),
        draw(st.sampled_from(_TAX_YEARS)),
    )


_txns = st.lists(_txn(), min_size=1, max_size=10)

# Per-year allowed mode: none, an explicit fraction of the loss, or fully.
_allowed_modes = st.sampled_from(
    ["none", "none", "partial_quarter", "partial_half", "fully"]
)
# Per-year reported choice.
_report_choices = st.sampled_from(
    [
        "unreported",
        "expected",
        "expected_up",
        "expected_down",
        "chain",
        "chain",
        "chain_up",
        "chain_down",
    ]
)


def _iso_date(year: int, index: int) -> str:
    return f"{year:04d}-{(index % 12) + 1:02d}-{(index % 28) + 1:02d}"


def _cents(value: Decimal) -> int:
    return int((value / _CENTS).to_integral_value())


def _money(cents: int) -> Decimal:
    return Decimal(cents) * _CENTS


_TOLERANCE_CENTS = _cents(STATUS_TOLERANCE)
# Off-by variants must differ by MORE than the tolerance to leave its band.
_VARIANT_CENTS = _TOLERANCE_CENTS + 1


def _within(a: int, b: int) -> bool:
    """Independent tolerance rule in integer cents: |a - b| <= tolerance."""
    return abs(a - b) <= _TOLERANCE_CENTS


def _step_cents(prior: int, net: int, allowed: int) -> int:
    """Independent oracle year step, integer cents."""
    if net < 0:
        return prior + max(-net - allowed, 0)
    return max(prior - net, 0)


# Feature: carryforward-chain-status, Property 1: Status follows the four-rule
# precedence and is total
# **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7**
@settings(deadline=None, max_examples=100)
@given(
    txns=_txns,
    opening=_opening,
    allowed_modes=st.lists(_allowed_modes, min_size=1, max_size=10),
    report_choices=st.lists(_report_choices, min_size=1, max_size=10),
)
def test_status_follows_four_rule_precedence_and_is_total(
    txns: list[tuple[str, str, Decimal, int]],
    opening: Decimal,
    allowed_modes: list[str],
    report_choices: list[str],
) -> None:
    """Every year's status equals the independent four-rule cents oracle.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7**
    """
    with _moto_service() as (service, properties, transactions):
        created = properties.create(
            PropertyInput(
                name="Prop0",
                address_text="1 Main St",
                property_type="single_family",
            )
        )
        assert created.is_ok, created.error
        pid = created.value.id
        for index, (ttype, category, amount, year) in enumerate(txns):
            result = transactions.create(
                TransactionInput(
                    property_id=pid,
                    date=_iso_date(year, index),
                    amount=amount,
                    type=ttype,
                    category_id=category,
                )
            )
            assert result.is_ok, result.error

        assert service.set_opening_balance(f"{opening:.2f}").is_ok

        # Learn the nets, then record allowed data for loss years.
        years = service.reconcile().years
        allowed_cents: dict[int, int] = {}
        for index, year in enumerate(years):
            net = _cents(year.schedule_e_net)
            mode = allowed_modes[index % len(allowed_modes)]
            allowed = 0
            if net < 0 and mode == "fully":
                assert service.set_fully_allowed(year.tax_year, True).is_ok
                allowed = -net
            elif net < 0 and mode in ("partial_quarter", "partial_half"):
                allowed = (-net) // (4 if mode == "partial_quarter" else 2)
                result = service.set_allowed_loss(
                    year.tax_year, f"{_money(allowed):.2f}"
                )
                assert result.is_ok, result.error
            allowed_cents[year.tax_year] = allowed

        # Walk the series with the oracle, choosing and recording reported
        # values from its expected and chain figures.
        years = service.reconcile().years
        balance = _cents(opening)
        prior_reported: int | None = None
        prior_net = 0
        prior_allowed = 0
        oracle_status: dict[int, str] = {}
        for index, year in enumerate(years):
            net = _cents(year.schedule_e_net)
            allowed = allowed_cents[year.tax_year]
            # Reported is the carry-in; compare with the balance entering.
            expected = balance
            balance = _step_cents(balance, net, allowed)
            chain = (
                _step_cents(prior_reported, prior_net, prior_allowed)
                if index > 0 and prior_reported is not None
                else None
            )
            assert year.expected_carry_in == _money(expected), year.tax_year
            assert year.expected_carryforward == _money(balance), (
                year.tax_year
            )

            choice = report_choices[index % len(report_choices)]
            reported: int | None
            if choice == "unreported":
                reported = None
            else:
                base = expected if choice.startswith("expected") else chain
                if base is None:
                    base = expected  # no chain available; fall back
                if choice.endswith("_up"):
                    base += _VARIANT_CENTS
                elif choice.endswith("_down"):
                    base = (
                        base - _VARIANT_CENTS
                        if base >= _VARIANT_CENTS
                        else base + _VARIANT_CENTS
                    )
                reported = base
            if reported is not None:
                result = service.set_reported(
                    year.tax_year, f"{_money(reported):.2f}"
                )
                assert result.is_ok, result.error

            if reported is None:
                oracle_status[year.tax_year] = "unreported"
            elif _within(reported, expected):
                oracle_status[year.tax_year] = "ok"
            elif chain is not None and _within(reported, chain):
                oracle_status[year.tax_year] = "carried"
            else:
                oracle_status[year.tax_year] = "mismatch"
            prior_reported = reported
            prior_net, prior_allowed = net, allowed

        final = service.reconcile().years
        assert [y.tax_year for y in final] == [y.tax_year for y in years]
        for year in final:
            assert year.status in {"ok", "mismatch", "carried", "unreported"}
            assert year.status == oracle_status[year.tax_year], (
                year.tax_year,
                year.status,
                oracle_status[year.tax_year],
            )


# --- Properties 4 and 5 -------------------------------------------------------


def _build_and_reconcile(
    txns: list[tuple[str, str, Decimal, int]],
    opening: Decimal,
    allowed_modes: list[str],
    report_choices: list[str],
):
    """Build a scenario in moto and return (final years, allowed cents, reported).

    Reuses the strategies and helpers above. Reported values are chosen from
    the oracle's expected and chain figures (and off-by-one-cent variants), so
    ``carried`` years occur often. ``reported`` maps year -> cents or None.
    """
    with _moto_service() as (service, properties, transactions):
        created = properties.create(
            PropertyInput(
                name="Prop0",
                address_text="1 Main St",
                property_type="single_family",
            )
        )
        assert created.is_ok, created.error
        pid = created.value.id
        for index, (ttype, category, amount, year) in enumerate(txns):
            result = transactions.create(
                TransactionInput(
                    property_id=pid,
                    date=_iso_date(year, index),
                    amount=amount,
                    type=ttype,
                    category_id=category,
                )
            )
            assert result.is_ok, result.error

        assert service.set_opening_balance(f"{opening:.2f}").is_ok

        years = service.reconcile().years
        allowed_cents: dict[int, int] = {}
        for index, year in enumerate(years):
            net = _cents(year.schedule_e_net)
            mode = allowed_modes[index % len(allowed_modes)]
            allowed = 0
            if net < 0 and mode == "fully":
                assert service.set_fully_allowed(year.tax_year, True).is_ok
                allowed = -net
            elif net < 0 and mode in ("partial_quarter", "partial_half"):
                allowed = (-net) // (4 if mode == "partial_quarter" else 2)
                result = service.set_allowed_loss(
                    year.tax_year, f"{_money(allowed):.2f}"
                )
                assert result.is_ok, result.error
            allowed_cents[year.tax_year] = allowed

        years = service.reconcile().years
        balance = _cents(opening)
        prior_reported: int | None = None
        prior_net = 0
        prior_allowed = 0
        reported_map: dict[int, int | None] = {}
        for index, year in enumerate(years):
            net = _cents(year.schedule_e_net)
            allowed = allowed_cents[year.tax_year]
            expected = balance  # carry-in expected for this year
            balance = _step_cents(balance, net, allowed)
            chain = (
                _step_cents(prior_reported, prior_net, prior_allowed)
                if index > 0 and prior_reported is not None
                else None
            )
            choice = report_choices[index % len(report_choices)]
            reported: int | None
            if choice == "unreported":
                reported = None
            else:
                base = expected if choice.startswith("expected") else chain
                if base is None:
                    base = expected
                if choice.endswith("_up"):
                    base += _VARIANT_CENTS
                elif choice.endswith("_down"):
                    base = (
                        base - _VARIANT_CENTS
                        if base >= _VARIANT_CENTS
                        else base + _VARIANT_CENTS
                    )
                reported = base
            if reported is not None:
                result = service.set_reported(
                    year.tax_year, f"{_money(reported):.2f}"
                )
                assert result.is_ok, result.error
            reported_map[year.tax_year] = reported
            prior_reported = reported
            prior_net, prior_allowed = net, allowed

        final = service.reconcile().years
        return final, allowed_cents, reported_map


_scenario_args = dict(
    txns=_txns,
    opening=_opening,
    allowed_modes=st.lists(_allowed_modes, min_size=1, max_size=10),
    report_choices=st.lists(_report_choices, min_size=1, max_size=10),
)


# Feature: carryforward-chain-status, Property 4: Carried implies the chain
# relation
# **Validates: Requirements 2.3**
@settings(deadline=None, max_examples=100)
@given(**_scenario_args)
def test_carried_implies_chain_relation(
    txns: list[tuple[str, str, Decimal, int]],
    opening: Decimal,
    allowed_modes: list[str],
    report_choices: list[str],
) -> None:
    """A carried year is non-first, follows a reported year, differs from
    expected, and equals this year's step on the prior reported value.

    **Validates: Requirements 2.3**
    """
    final, allowed_cents, _ = _build_and_reconcile(
        txns, opening, allowed_modes, report_choices
    )
    for index, year in enumerate(final):
        if year.status != "carried":
            continue
        assert index > 0, year.tax_year
        prior = final[index - 1]
        assert prior.reported_carryforward is not None, year.tax_year
        assert year.reported_carryforward is not None, year.tax_year
        assert not _within(
            _cents(year.reported_carryforward), _cents(year.expected_carry_in)
        )
        # Previous year's step applied to the previous reported carry-in.
        chain = _step_cents(
            _cents(prior.reported_carryforward),
            _cents(prior.schedule_e_net),
            allowed_cents[prior.tax_year],
        )
        assert _within(_cents(year.reported_carryforward), chain), year.tax_year


# Feature: carryforward-chain-status, Property 5: Root-cause attribution
# **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
@settings(deadline=None, max_examples=100)
@given(**_scenario_args)
def test_carried_from_year_is_most_recent_earlier_mismatch(
    txns: list[tuple[str, str, Decimal, int]],
    opening: Decimal,
    allowed_modes: list[str],
    report_choices: list[str],
) -> None:
    """carried_from_year is the latest earlier mismatch year for carried
    years, strictly earlier than the year, and null otherwise.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """
    final, _, _ = _build_and_reconcile(
        txns, opening, allowed_modes, report_choices
    )
    last_mismatch: int | None = None
    for year in final:
        if year.status == "carried":
            assert year.carried_from_year == last_mismatch, year.tax_year
            assert year.carried_from_year is not None, year.tax_year
            assert year.carried_from_year < year.tax_year
        else:
            assert year.carried_from_year is None, year.tax_year
        if year.status == "mismatch":
            last_mismatch = year.tax_year
