"""Property-based tests for the allowed-loss carryforward engine.

These tests exercise ``CarryforwardService.reconcile()`` with per-year
allowed data (``Allowed_Loss`` amounts and ``Fully_Allowed`` flags) layered
onto a deliberately mixed series of loss and gain years across non-contiguous
tax years. Each Hypothesis example provisions its own moto-backed single-table
DynamoDB (base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, composing the real ``CarryforwardService`` /
``PropertyService`` / ``ReportingService`` stack exactly as the carryforward
route does — mirroring ``test_carryforward_running_balance_property.py``.

Per-example provisioning is not instantaneous, so the deadline is disabled; the
example count is held at 100.
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

# A small spread of distinct, deliberately non-contiguous tax years the
# generated transactions are dated within, so the reconciled series spans
# several Data_Years with gaps.
_TAX_YEARS = [2020, 2022, 2023, 2025]

_CENTS = Decimal("0.01")
_ZERO = Decimal("0.00")


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed CarryforwardService bound to freshly created resources
    so each Hypothesis example runs against a clean store. The service is
    constructed exactly as the carryforward route composes it:
    ``CarryforwardService(repo, USER, reports, properties, transactions,
    depreciation)``.
    """
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
#
# Each transaction is a (type, category, amount, description, year) tuple, using
# a spread of known, valid categories so the amount / missing-field /
# unknown-category paths never confound this property. A deliberate mix of
# income and expense lines across the non-contiguous tax years produces varied
# per-year nets (some loss years, some gain years).
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

# A non-negative two-decimal Opening_Balance set via set_opening_balance.
_opening_amounts = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# A fraction in [0, 1] (as an exact numerator/denominator pair) used to draw an
# allowed amount from a loss year's magnitude; combined with a "how to allow"
# choice below. Represented as (numerator, denominator) integers so the amount
# is computed with exact integer-cents arithmetic (no float, no Fraction→Decimal
# conversion).
@st.composite
def _ratio(draw: st.DrawFn) -> tuple[int, int]:
    """An exact ratio in [0, 1] as (numerator, denominator) integers."""
    denominator = draw(st.integers(min_value=1, max_value=100))
    numerator = draw(st.integers(min_value=0, max_value=denominator))
    return numerator, denominator

# Per loss year, one of: skip (no allowed data), set an explicit Allowed_Loss in
# [0, loss_magnitude], or turn on Fully_Allowed.
_ALLOW_MODES = ["skip", "amount", "fully"]


@st.composite
def _txn(draw: st.DrawFn) -> tuple[str, str, Decimal, str | None, int]:
    """One (type, category_id, amount, description, tax_year) transaction spec."""
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


def _iso_date(year: int, index: int) -> str:
    """A deterministic in-year ISO date, cycling day/month to stay valid."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


# Feature: carryforward-allowed-loss, Property 1: Suspended loss is the floored
# unallowed portion and the balance stays non-negative
@settings(deadline=None, max_examples=100)
@given(
    properties_txns=st.lists(_property_txns, min_size=1, max_size=4),
    opening=_opening_amounts,
    allow_plan=st.lists(
        st.tuples(st.sampled_from(_ALLOW_MODES), _ratio()),
        min_size=len(_TAX_YEARS),
        max_size=len(_TAX_YEARS),
    ),
)
def test_suspended_is_floored_unallowed_portion_and_balance_non_negative(
    properties_txns: list[list[tuple[str, str, Decimal, str | None, int]]],
    opening: Decimal,
    allow_plan: list[tuple[str, tuple[int, int]]],
) -> None:
    """Suspended == floored unallowed portion; balance stays non-negative.

    Validates: Requirements 3.1, 3.2, 3.4, 3.5, 9.2
    """
    with _moto_service() as (service, properties, transactions):
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

            for t_index, (ttype, category, amount, description, year) in enumerate(
                txns
            ):
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

        # Seed the Opening_Balance through the real service path.
        opening_result = service.set_opening_balance(f"{opening:.2f}")
        assert opening_result.is_ok, opening_result.error

        # Reconcile once to learn each year's Schedule_E_Net so the allowed
        # amounts can be composed from the real loss magnitudes (so the service
        # accepts them — validation caps an amount at the loss magnitude).
        first = service.reconcile()

        # Map each year's plan by ascending year position, so the per-year plan
        # tuple lines up with the reconciled series deterministically.
        plan_by_year: dict[int, tuple[str, tuple[int, int]]] = {}
        for reconciled, plan in zip(first.years, allow_plan):
            plan_by_year[reconciled.tax_year] = plan

        for reconciled in first.years:
            net = reconciled.schedule_e_net
            if net >= 0:
                # Non_Loss_Year: no allowed data applies (the service would
                # reject it). Leave it alone.
                continue
            loss_magnitude = -net
            mode, (numerator, denominator) = plan_by_year.get(
                reconciled.tax_year, ("skip", (0, 1))
            )
            if mode == "amount":
                # Draw allowed in [0, loss_magnitude] with exact integer-cents
                # arithmetic, so the service accepts it (validation caps the
                # amount at the loss magnitude).
                magnitude_cents = int((loss_magnitude / _CENTS).to_integral_value())
                allowed_cents = magnitude_cents * numerator // denominator
                allowed = Decimal(allowed_cents) * _CENTS
                set_result = service.set_allowed_loss(
                    reconciled.tax_year, f"{allowed:.2f}"
                )
                assert set_result.is_ok, (reconciled.tax_year, set_result.error)
            elif mode == "fully":
                set_result = service.set_fully_allowed(
                    reconciled.tax_year, True
                )
                assert set_result.is_ok, (reconciled.tax_year, set_result.error)
            # mode == "skip": leave the year with no allowed data.

        # Reconcile again with the allowed data in place.
        summary = service.reconcile()

        assert summary.opening_balance == opening

        # Walk the returned years ascending, re-deriving an independent
        # Decimal-cents oracle from each year's returned schedule_e_net,
        # allowed_loss, and fully_allowed, starting from the Opening_Balance.
        prior_balance = summary.opening_balance
        prev_year: int | None = None
        for reconciled in summary.years:
            if prev_year is not None:
                assert reconciled.tax_year > prev_year, (
                    prev_year,
                    reconciled.tax_year,
                )
            prev_year = reconciled.tax_year

            net = reconciled.schedule_e_net
            if net < 0:
                # Loss_Year: effective allowed is the full magnitude when
                # fully_allowed, otherwise the stored allowed_loss (Req 3.1).
                loss_magnitude = -net
                if reconciled.fully_allowed:
                    effective_allowed = loss_magnitude
                else:
                    effective_allowed = reconciled.allowed_loss
                suspended = max(loss_magnitude - effective_allowed, _ZERO)
                oracle = prior_balance + suspended
            else:
                # Non_Loss_Year: a gain is absorbed, floored at zero (Req 3.2).
                oracle = max(prior_balance - net, _ZERO)

            # The step relation holds exactly to the cent (Req 3.1, 3.2).
            assert reconciled.expected_carryforward == oracle, (
                reconciled.tax_year,
                prior_balance,
                net,
                reconciled.allowed_loss,
                reconciled.fully_allowed,
                reconciled.expected_carryforward,
                oracle,
            )

            # Expected and the running balance are never negative (Req 3.4,
            # 9.2) and are two-decimal Decimals (exponent -2) (Req 3.5).
            assert reconciled.expected_carryforward >= _ZERO, (
                reconciled.tax_year,
                reconciled.expected_carryforward,
            )
            assert oracle >= _ZERO, (reconciled.tax_year, oracle)
            assert isinstance(reconciled.expected_carryforward, Decimal)
            assert reconciled.expected_carryforward.as_tuple().exponent == -2, (
                reconciled.tax_year,
                reconciled.expected_carryforward,
            )

            # Each year's expected is the balance carried into the next year.
            prior_balance = reconciled.expected_carryforward


# Feature: carryforward-allowed-loss, Property 2: Backward compatibility — no
# allowed data reproduces today's series exactly
@settings(deadline=None, max_examples=100)
@given(
    properties_txns=st.lists(_property_txns, min_size=1, max_size=4),
    opening=_opening_amounts,
    # Per ascending-year position: whether to set a reported value on that year,
    # and if so a ratio used to derive it from the year's expected (so some
    # reported values land exactly on expected → ok, others deliberately off →
    # mismatch), exercising all three statuses without any allowed data.
    report_plan=st.lists(
        st.tuples(st.booleans(), _ratio()),
        min_size=len(_TAX_YEARS),
        max_size=len(_TAX_YEARS),
    ),
)
def test_no_allowed_data_reproduces_pre_feature_series_exactly(
    properties_txns: list[list[tuple[str, str, Decimal, str | None, int]]],
    opening: Decimal,
    report_plan: list[tuple[bool, tuple[int, int]]],
) -> None:
    """With NO allowed data, the series equals the pre-feature recurrence.

    Never calls set_allowed_loss / set_fully_allowed on any year. The reconciled
    expected_carryforward series must be byte-for-byte identical to the
    pre-feature running-balance recurrence over the returned nets + opening
    balance: a loss adds its full magnitude; a gain is absorbed, floored at
    0.00 (NO allowed subtraction). ``unreported`` and ``ok`` statuses match the
    pre-feature rule exactly; a pre-feature ``mismatch`` is ``mismatch`` or
    ``carried`` (chain check). Each year's allowed_loss must read as the 0.00
    default and fully_allowed as False (absent → defaults, Req 7.2).

    Validates: Requirements 7.1, 7.2, 7.3, 9.3
    """
    with _moto_service() as (service, properties, transactions):
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

            for t_index, (ttype, category, amount, description, year) in enumerate(
                txns
            ):
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

        # Seed the Opening_Balance through the real service path.
        opening_result = service.set_opening_balance(f"{opening:.2f}")
        assert opening_result.is_ok, opening_result.error

        # Reconcile once to learn each year's expected (NO allowed data set),
        # so reported values can be composed from the real expected magnitudes
        # (some landing exactly on expected → ok, others off → mismatch).
        first = service.reconcile()

        plan_by_year: dict[int, tuple[bool, tuple[int, int]]] = {}
        for reconciled, plan in zip(first.years, report_plan):
            plan_by_year[reconciled.tax_year] = plan

        # Set reported values on a subset of years to exercise ok / mismatch,
        # leaving the rest unreported. Crucially, NEVER touch allowed data.
        for reconciled in first.years:
            do_report, (numerator, denominator) = plan_by_year.get(
                reconciled.tax_year, (False, (0, 1))
            )
            if not do_report:
                continue
            # The reported value is the Form 8582 carry-IN, so it is composed
            # from (and later compared with) the year's expected carry-in.
            expected = reconciled.expected_carry_in
            if numerator == denominator:
                # Exactly on expected → ok.
                reported = expected
            else:
                # A non-negative fraction of expected, generally != expected →
                # mismatch (and still a valid non-negative two-decimal amount).
                expected_cents = int((expected / _CENTS).to_integral_value())
                reported_cents = expected_cents * numerator // denominator
                reported = Decimal(reported_cents) * _CENTS
            set_result = service.set_reported(
                reconciled.tax_year, f"{reported:.2f}"
            )
            assert set_result.is_ok, (reconciled.tax_year, set_result.error)

        # Reconcile again — reported values present, still NO allowed data.
        summary = service.reconcile()

        assert summary.opening_balance == opening

        # Walk ascending, computing the pre-feature oracle independently:
        # loss → balance += -net; gain → balance = max(balance - net, 0.00).
        # No allowed subtraction whatsoever.
        oracle_balance = summary.opening_balance
        prev_year: int | None = None
        for reconciled in summary.years:
            if prev_year is not None:
                assert reconciled.tax_year > prev_year, (
                    prev_year,
                    reconciled.tax_year,
                )
            prev_year = reconciled.tax_year

            net = reconciled.schedule_e_net
            if net < 0:
                oracle_balance = oracle_balance + (-net)
            else:
                oracle_balance = max(oracle_balance - net, _ZERO)

            # Expected equals the pre-feature recurrence to the cent (Req 7.1,
            # 7.3, 9.3).
            assert reconciled.expected_carryforward == oracle_balance, (
                reconciled.tax_year,
                net,
                reconciled.expected_carryforward,
                oracle_balance,
            )

            # Absent allowed data reads as its defaults (Req 7.2).
            assert reconciled.allowed_loss == _ZERO, (
                reconciled.tax_year,
                reconciled.allowed_loss,
            )
            assert reconciled.fully_allowed is False, (
                reconciled.tax_year,
                reconciled.fully_allowed,
            )

            # Status under carry-in semantics: unreported when no reported;
            # ok when reported is within STATUS_TOLERANCE of expected carry-in;
            # else mismatch, which the
            # chain check may relabel as ``carried`` (carry-in Req 3.1-3.4).
            reported = reconciled.reported_carryforward
            if reported is None:
                allowed_statuses = {"unreported"}
            elif abs(reported - reconciled.expected_carry_in) <= STATUS_TOLERANCE:
                allowed_statuses = {"ok"}
            else:
                allowed_statuses = {"mismatch", "carried"}
            assert reconciled.status in allowed_statuses, (
                reconciled.tax_year,
                reconciled.status,
                allowed_statuses,
                reported,
                reconciled.expected_carry_in,
            )
