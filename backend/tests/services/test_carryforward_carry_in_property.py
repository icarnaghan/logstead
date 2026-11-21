"""Property-based tests: carry-in semantics of the carryforward reconciliation.

Feature: carryforward-carry-in-semantics, Properties 1, 3 and 8.

* Property 1: the first year's ``expected_carry_in`` is the opening balance,
  each later year's equals the previous year's ``expected_carryforward``, and
  ``expected_carryforward`` equals an independent integer-cents running-balance
  recurrence, regardless of reported data.
* Property 3: when every year's reported value equals its
  ``expected_carry_in``, every year is ``ok`` with drift ``0.00``.
* Property 8: ``next_year`` / ``next_year_expected_carry_in`` follow the latest
  year (or are ``None`` / the opening balance for an empty series).

The oracle works in integer cents from the returned nets and the allowed data
this test set; it never calls ``_apply_year_step`` or ``_effective_allowed``.

Mirrors the moto-backed composition in
``test_carryforward_chain_status_property.py``.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 3.8, 6.1, 7.3, 7.4, 7.5**
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
from logstead.services.carryforward import CarryforwardService
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


# min_size=0 so the empty series (Property 8) is exercised.
_txns = st.lists(_txn(), min_size=0, max_size=10)
_txns_nonempty = st.lists(_txn(), min_size=1, max_size=10)

_allowed_modes = st.sampled_from(
    ["none", "none", "partial_quarter", "partial_half", "fully"]
)
# Per-year reported choice for Property 1 (reported data must not matter).
_report_choices = st.sampled_from(["unreported", "arbitrary", "arbitrary"])
_arbitrary_cents = st.integers(min_value=0, max_value=10_000_000)


def _iso_date(year: int, index: int) -> str:
    return f"{year:04d}-{(index % 12) + 1:02d}-{(index % 28) + 1:02d}"


def _cents(value: Decimal) -> int:
    return int((value / _CENTS).to_integral_value())


def _money(cents: int) -> Decimal:
    return Decimal(cents) * _CENTS


def _step_cents(prior: int, net: int, allowed: int) -> int:
    """Independent oracle year step, integer cents."""
    if net < 0:
        return prior + max(-net - allowed, 0)
    return max(prior - net, 0)


def _build(service, properties, transactions, txns, opening, allowed_modes):
    """Create data, set opening balance and allowed data.

    Returns the allowed-cents map keyed by tax year.
    """
    if txns:
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

    allowed_cents: dict[int, int] = {}
    for index, year in enumerate(service.reconcile().years):
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
    return allowed_cents


# Feature: carryforward-carry-in-semantics, Property 1: Carry-in follows the
# previous carry-out and carry-out is unchanged
# **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
@settings(deadline=None, max_examples=100)
@given(
    txns=_txns_nonempty,
    opening=_opening,
    allowed_modes=st.lists(_allowed_modes, min_size=1, max_size=10),
    report_choices=st.lists(_report_choices, min_size=1, max_size=10),
    report_values=st.lists(_arbitrary_cents, min_size=1, max_size=10),
)
def test_carry_in_follows_previous_carry_out(
    txns: list[tuple[str, str, Decimal, int]],
    opening: Decimal,
    allowed_modes: list[str],
    report_choices: list[str],
    report_values: list[int],
) -> None:
    """Carry-in chain and the unchanged carry-out match the cents oracle.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
    """
    with _moto_service() as (service, properties, transactions):
        allowed_cents = _build(
            service, properties, transactions, txns, opening, allowed_modes
        )
        # Arbitrary reported data must not influence the expected figures.
        for index, year in enumerate(service.reconcile().years):
            if report_choices[index % len(report_choices)] == "arbitrary":
                value = report_values[index % len(report_values)]
                result = service.set_reported(
                    year.tax_year, f"{_money(value):.2f}"
                )
                assert result.is_ok, result.error

        years = service.reconcile().years
        assert years
        balance = _cents(opening)
        previous_out: Decimal | None = None
        for index, year in enumerate(years):
            net = _cents(year.schedule_e_net)
            expected_in = balance
            balance = _step_cents(balance, net, allowed_cents[year.tax_year])

            assert year.expected_carry_in == _money(expected_in), year.tax_year
            assert year.expected_carryforward == _money(balance), year.tax_year
            if index == 0:
                assert year.expected_carry_in == opening
            else:
                assert year.expected_carry_in == previous_out, year.tax_year
            # Exact two-decimal Decimal values.
            assert year.expected_carry_in == year.expected_carry_in.quantize(
                _CENTS
            )
            assert year.expected_carryforward == (
                year.expected_carryforward.quantize(_CENTS)
            )
            previous_out = year.expected_carryforward


# Feature: carryforward-carry-in-semantics, Property 3: Faithful entry is all ok
# **Validates: Requirements 3.8, 6.1**
@settings(deadline=None, max_examples=100)
@given(
    txns=_txns_nonempty,
    opening=_opening,
    allowed_modes=st.lists(_allowed_modes, min_size=1, max_size=10),
)
def test_faithful_entry_is_all_ok(
    txns: list[tuple[str, str, Decimal, int]],
    opening: Decimal,
    allowed_modes: list[str],
) -> None:
    """Reporting each year's expected carry-in yields all ``ok`` and drift 0.

    **Validates: Requirements 3.8, 6.1**
    """
    with _moto_service() as (service, properties, transactions):
        allowed_cents = _build(
            service, properties, transactions, txns, opening, allowed_modes
        )
        years = service.reconcile().years
        balance = _cents(opening)
        for year in years:
            result = service.set_reported(
                year.tax_year, f"{_money(balance):.2f}"
            )
            assert result.is_ok, result.error
            balance = _step_cents(
                balance,
                _cents(year.schedule_e_net),
                allowed_cents[year.tax_year],
            )

        final = service.reconcile().years
        assert [y.tax_year for y in final] == [y.tax_year for y in years]
        for year in final:
            assert year.status == "ok", (year.tax_year, year.status)
            assert year.drift == Decimal("0.00"), year.tax_year
            assert year.carried_from_year is None, year.tax_year
            assert year.reported_carryforward == year.expected_carry_in


# Feature: carryforward-carry-in-semantics, Property 8: Next-year expectation
# **Validates: Requirements 7.3, 7.4, 7.5**
@settings(deadline=None, max_examples=100)
@given(
    txns=_txns,
    opening=_opening,
    allowed_modes=st.lists(_allowed_modes, min_size=1, max_size=10),
)
def test_next_year_expectation(
    txns: list[tuple[str, str, Decimal, int]],
    opening: Decimal,
    allowed_modes: list[str],
) -> None:
    """Summary next-year fields follow the latest year, or the opening balance.

    **Validates: Requirements 7.3, 7.4, 7.5**
    """
    with _moto_service() as (service, properties, transactions):
        allowed_cents = _build(
            service, properties, transactions, txns, opening, allowed_modes
        )
        summary = service.reconcile()
        years = summary.years
        assert isinstance(summary.next_year_expected_carry_in, Decimal)
        if years:
            balance = _cents(opening)
            for year in years:
                balance = _step_cents(
                    balance,
                    _cents(year.schedule_e_net),
                    allowed_cents[year.tax_year],
                )
            assert summary.next_year == years[-1].tax_year + 1
            assert summary.next_year_expected_carry_in == years[
                -1
            ].expected_carryforward
            assert summary.next_year_expected_carry_in == _money(balance)
        else:
            assert summary.next_year is None
            assert summary.next_year_expected_carry_in == opening
