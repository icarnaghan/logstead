"""Property-based compatibility tests for carryforward chain status.

These tests exercise ``CarryforwardService.reconcile()`` against an independent
oracle of the *pre-feature* running-balance recurrence for
``expected_carryforward`` (the carry-out, with allowed-loss handling), which
must be unchanged by the carry-in semantics feature.

Status is re-pointed to carry-in semantics: the reported value is the Form 8582
"Prior years unallowed losses" carry-in and is compared with
``expected_carry_in`` (the previous year's carry-out, or the opening balance
for the first year). ``unreported`` holds iff nothing is reported, ``ok`` iff
reported is within ``STATUS_TOLERANCE`` of ``expected_carry_in``, and
``mismatch`` / ``carried`` are the cases outside it. When no reported year has
a reported prior year, no chain rule applies, so every status is ``ok``,
``mismatch`` or ``unreported``.

Backward compatibility: exact-equal years are ``ok``, ``unreported`` years are
unchanged, a year that was exact ``carried`` and is not within tolerance of
expected is still ``carried``, and with ``STATUS_TOLERANCE`` patched to
``0.00`` the old exact classification is reproduced. ``expected_carryforward``
recurrence assertions stay exact to the cent.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket, composing the real service stack the
carryforward route uses, mirroring
``test_carryforward_allowed_balance_property.py``.
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
from logstead.services import carryforward as carryforward_module
from logstead.services.carryforward import STATUS_TOLERANCE, CarryforwardService
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"

_TAX_YEARS = [2020, 2022, 2023, 2025]

_CENTS = Decimal("0.01")
_ZERO = Decimal("0.00")


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB + S3 and yield composed services."""
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
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_INCOME_SPECS = [("income", "rents-received"), ("income", "royalties-received")]
_EXPENSE_SPECS = [
    ("expense", "repairs"),
    ("expense", "utilities"),
    ("expense", "other"),
]

_opening_amounts = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def _ratio(draw: st.DrawFn) -> tuple[int, int]:
    """An exact ratio in [0, 1] as (numerator, denominator) integers."""
    denominator = draw(st.integers(min_value=1, max_value=100))
    numerator = draw(st.integers(min_value=0, max_value=denominator))
    return numerator, denominator


_ALLOW_MODES = ["skip", "amount", "fully"]

# How to report a year: leave it, report exactly expected, or report expected
# shifted by a signed number of cents (floored at zero).
_REPORT_MODES = ["unreported", "expected", "shifted"]


@st.composite
def _txn(draw: st.DrawFn) -> tuple[str, str, Decimal, str | None, int]:
    ttype, category = draw(st.sampled_from(_INCOME_SPECS + _EXPENSE_SPECS))
    amount = draw(_amounts)
    year = draw(st.sampled_from(_TAX_YEARS))
    description: str | None = None
    if category == "other":
        description = draw(
            st.text(min_size=1, max_size=20).filter(lambda s: s.strip())
        )
    return ttype, category, amount, description, year


_property_txns = st.lists(_txn(), min_size=0, max_size=10)

_report_plan = st.lists(
    st.tuples(
        st.sampled_from(_REPORT_MODES),
        st.integers(min_value=-500, max_value=500),
    ),
    min_size=len(_TAX_YEARS),
    max_size=len(_TAX_YEARS),
)

_allow_plan = st.lists(
    st.tuples(st.sampled_from(_ALLOW_MODES), _ratio()),
    min_size=len(_TAX_YEARS),
    max_size=len(_TAX_YEARS),
)


def _iso_date(year: int, index: int) -> str:
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _seed(service, properties, transactions, properties_txns, opening) -> None:
    for p_index, txns in enumerate(properties_txns):
        created = properties.create(
            PropertyInput(
                name=f"Prop{p_index}",
                address_text=f"{p_index} Main St",
                property_type="single_family",
            )
        )
        assert created.is_ok, created.error
        pid = created.value.id
        for t_index, (ttype, category, amount, description, year) in enumerate(txns):
            result = transactions.create(
                TransactionInput(
                    property_id=pid,
                    date=_iso_date(year, t_index),
                    amount=amount,
                    type=ttype,
                    category_id=category,
                    description=description,
                )
            )
            assert result.is_ok, result.error
    opening_result = service.set_opening_balance(f"{opening:.2f}")
    assert opening_result.is_ok, opening_result.error


def _apply_allowed(service, allow_plan) -> None:
    """Set allowed data on loss years according to the plan."""
    first = service.reconcile()
    for reconciled, (mode, (numerator, denominator)) in zip(first.years, allow_plan):
        net = reconciled.schedule_e_net
        if net >= 0:
            continue
        if mode == "amount":
            magnitude_cents = int(((-net) / _CENTS).to_integral_value())
            allowed = Decimal(magnitude_cents * numerator // denominator) * _CENTS
            res = service.set_allowed_loss(reconciled.tax_year, f"{allowed:.2f}")
            assert res.is_ok, (reconciled.tax_year, res.error)
        elif mode == "fully":
            res = service.set_fully_allowed(reconciled.tax_year, True)
            assert res.is_ok, (reconciled.tax_year, res.error)


def _apply_reports(service, report_plan, eligible=lambda index: True) -> None:
    """Set reported values per the plan on years where ``eligible(index)``."""
    first = service.reconcile()
    for index, (reconciled, (mode, shift)) in enumerate(
        zip(first.years, report_plan)
    ):
        if mode == "unreported" or not eligible(index):
            continue
        expected = reconciled.expected_carry_in
        if mode == "expected":
            reported = expected
        else:
            reported = max(expected + Decimal(shift) * _CENTS, _ZERO)
        res = service.set_reported(reconciled.tax_year, f"{reported:.2f}")
        assert res.is_ok, (reconciled.tax_year, res.error)


def _old_expected_series(summary) -> list[Decimal]:
    """Pre-feature recurrence over the returned nets and allowed data."""
    balance = summary.opening_balance
    out: list[Decimal] = []
    for y in summary.years:
        net = y.schedule_e_net
        if net < 0:
            magnitude = -net
            allowed = magnitude if y.fully_allowed else y.allowed_loss
            balance = balance + max(magnitude - allowed, _ZERO)
        else:
            balance = max(balance - net, _ZERO)
        out.append(balance)
    return out


def _carry_in_series(summary, carry_out: list[Decimal]) -> list[Decimal]:
    """Expected carry-in: opening balance, then each previous carry-out."""
    return [summary.opening_balance, *carry_out[:-1]][: len(carry_out)]


def _status_vs_carry_in(reported: Decimal | None, expected_in: Decimal) -> str:
    """Tolerance rule: ok when within STATUS_TOLERANCE of the carry-in."""
    if reported is None:
        return "unreported"
    return "ok" if abs(reported - expected_in) <= STATUS_TOLERANCE else "mismatch"


def _chain_in(years, index: int) -> Decimal | None:
    """Previous year's step applied to the previous year's reported value."""
    if index == 0:
        return None
    prior = years[index - 1]
    if prior.reported_carryforward is None:
        return None
    net = prior.schedule_e_net
    if net < 0:
        allowed = -net if prior.fully_allowed else prior.allowed_loss
        return prior.reported_carryforward + max(-net - allowed, _ZERO)
    return max(prior.reported_carryforward - net, _ZERO)


def _exact_status(years, index: int) -> str:
    """The pre-feature (exact-to-the-cent) four-rule classification."""
    reported = years[index].reported_carryforward
    if reported is None:
        return "unreported"
    if reported == years[index].expected_carry_in:
        return "ok"
    chain = _chain_in(years, index)
    if chain is not None and reported == chain:
        return "carried"
    return "mismatch"


# Feature: carryforward-chain-status, Property 2: Expected carryforward is
# unchanged
# Feature: carryforward-chain-status, Property 3: Backward compatibility of
# statuses
@settings(deadline=None, max_examples=100)
@given(
    properties_txns=st.lists(_property_txns, min_size=1, max_size=4),
    opening=_opening_amounts,
    allow_plan=_allow_plan,
    report_plan=_report_plan,
)
def test_expected_unchanged_and_statuses_backward_compatible(
    properties_txns: list[list[tuple[str, str, Decimal, str | None, int]]],
    opening: Decimal,
    allow_plan: list[tuple[str, tuple[int, int]]],
    report_plan: list[tuple[str, int]],
) -> None:
    """Carry-out matches the old recurrence; unreported/ok exact vs carry-in;
    a differing carry-in is mismatch or carried.

    Validates: Requirements 1.4, 3.1, 3.2
    """
    with _moto_service() as (service, properties, transactions):
        _seed(service, properties, transactions, properties_txns, opening)
        _apply_allowed(service, allow_plan)
        _apply_reports(service, report_plan)

        summary = service.reconcile()
        old_expected = _old_expected_series(summary)

        carry_in = _carry_in_series(summary, old_expected)
        for reconciled, expected, expected_in in zip(
            summary.years, old_expected, carry_in
        ):
            # Property 2: carry-out is the pre-feature recurrence, to the cent.
            assert reconciled.expected_carryforward == expected, (
                reconciled.tax_year,
                reconciled.expected_carryforward,
                expected,
            )
            assert reconciled.expected_carry_in == expected_in, (
                reconciled.tax_year,
                reconciled.expected_carry_in,
                expected_in,
            )

            # Property 3: status is re-pointed to the carry-in; chain only
            # splits "differs from expected carry-in" into mismatch/carried.
            base = _status_vs_carry_in(reconciled.reported_carryforward, expected_in)
            if base == "mismatch":
                assert reconciled.status in {"mismatch", "carried"}, (
                    reconciled.tax_year,
                    reconciled.status,
                )
            else:
                assert reconciled.status == base, (
                    reconciled.tax_year,
                    reconciled.status,
                    base,
                )

        # Backward compatibility with the exact (pre-tolerance) classification.
        for index, reconciled in enumerate(summary.years):
            old = _exact_status(summary.years, index)
            if old in {"ok", "unreported"}:
                assert reconciled.status == old, (reconciled.tax_year, old)
            elif old == "carried":
                reported = reconciled.reported_carryforward
                assert reported is not None
                if abs(reported - reconciled.expected_carry_in) > STATUS_TOLERANCE:
                    assert reconciled.status == "carried", reconciled.tax_year


# Feature: carryforward-tolerance-and-year-range, Property 6: with the
# tolerance patched to 0.00 the pre-feature exact classification is reproduced
@settings(deadline=None, max_examples=100)
@given(
    properties_txns=st.lists(_property_txns, min_size=1, max_size=4),
    opening=_opening_amounts,
    allow_plan=_allow_plan,
    report_plan=_report_plan,
)
def test_zero_tolerance_reproduces_exact_statuses(
    properties_txns: list[list[tuple[str, str, Decimal, str | None, int]]],
    opening: Decimal,
    allow_plan: list[tuple[str, tuple[int, int]]],
    report_plan: list[tuple[str, int]],
) -> None:
    """With STATUS_TOLERANCE patched to 0.00, statuses equal the exact rules.

    Validates: Requirements 3.4
    """
    with _moto_service() as (service, properties, transactions):
        _seed(service, properties, transactions, properties_txns, opening)
        _apply_allowed(service, allow_plan)
        _apply_reports(service, report_plan)

        original = carryforward_module.STATUS_TOLERANCE
        carryforward_module.STATUS_TOLERANCE = Decimal("0.00")
        try:
            summary = service.reconcile()
        finally:
            carryforward_module.STATUS_TOLERANCE = original

        assert summary.status_tolerance == Decimal("0.00")
        for index, reconciled in enumerate(summary.years):
            assert reconciled.status == _exact_status(summary.years, index), (
                reconciled.tax_year,
                reconciled.status,
            )


# Feature: carryforward-chain-status, Property 3: Backward compatibility of
# statuses (non-adjacent reported years)
@settings(deadline=None, max_examples=100)
@given(
    properties_txns=st.lists(_property_txns, min_size=1, max_size=4),
    opening=_opening_amounts,
    allow_plan=_allow_plan,
    report_plan=_report_plan,
    parity=st.integers(min_value=0, max_value=1),
)
def test_non_adjacent_reported_years_keep_pre_feature_statuses(
    properties_txns: list[list[tuple[str, str, Decimal, str | None, int]]],
    opening: Decimal,
    allow_plan: list[tuple[str, tuple[int, int]]],
    report_plan: list[tuple[str, int]],
    parity: int,
) -> None:
    """With reported values only on every other series position, no reported
    year has a reported prior year, so every status is ok/mismatch/unreported.

    Validates: Requirements 3.6
    """
    with _moto_service() as (service, properties, transactions):
        _seed(service, properties, transactions, properties_txns, opening)
        _apply_allowed(service, allow_plan)
        _apply_reports(
            service, report_plan, eligible=lambda index: index % 2 == parity
        )

        summary = service.reconcile()
        old_expected = _old_expected_series(summary)

        carry_in = _carry_in_series(summary, old_expected)
        for reconciled, expected, expected_in in zip(
            summary.years, old_expected, carry_in
        ):
            assert reconciled.expected_carryforward == expected, (
                reconciled.tax_year,
                reconciled.expected_carryforward,
                expected,
            )
            base = _status_vs_carry_in(reconciled.reported_carryforward, expected_in)
            assert reconciled.status == base, (
                reconciled.tax_year,
                reconciled.status,
                base,
            )
            assert reconciled.status != "carried"
