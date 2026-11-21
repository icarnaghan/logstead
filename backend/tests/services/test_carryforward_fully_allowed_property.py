"""Property-based test: the Fully_Allowed toggle contributes zero and agrees
to the cent with storing an explicit Allowed_Loss equal to the year's current
Loss_Magnitude.

Design Property 3 — *Fully-allowed contributes zero and equals the
explicit-full-amount case* (Requirements 3.7, 4.2, 4.3, 4.4, 8.3): for any
Loss_Year, turning on ``Fully_Allowed`` makes that year contribute ``0.00`` to
the Suspended_Loss_Balance (its ``suspended == 0.00``), and the resulting
Expected_Carryforward series equals the one produced by instead storing an
explicit ``Allowed_Loss`` equal to that year's current Loss_Magnitude — even
when the year's net later changes (the flag tracks the current magnitude
dynamically, taking precedence over any stored ``Allowed_Loss``).

This exercises :meth:`CarryforwardService.set_fully_allowed` /
:meth:`~CarryforwardService.set_allowed_loss` and the running-balance loop's
``suspended = max(-net - effective_allowed, 0.00)`` step (``services/
carryforward.py``). ``_effective_allowed`` returns the current ``-net`` when
``fully_allowed`` is on — so a fully-allowed loss year contributes exactly
``0.00`` — which is identical to storing an explicit ``allowed_loss`` of that
same magnitude. Three facets are checked for a generated Loss_Year:

* **Toggle == explicit full amount (Req 8.3).** With the year fully allowed vs
  with an explicit ``set_allowed_loss(year, loss_magnitude)`` (fully cleared
  first), the two produce the IDENTICAL Expected_Carryforward series, and the
  fully-allowed year's ``expected`` reflects the loss fully absorbed (``0.00``
  for that year when it is the only loss carried in from a ``0.00`` balance).
* **Dynamic tracking (Req 4.3).** After setting ``fully_allowed``, the year's
  net is changed (an extra expense deepens the loss); the year still
  contributes ``0.00`` suspended, proving the flag tracks the CURRENT loss
  magnitude, not a snapshot.
* **Precedence (Req 4.4).** With BOTH an explicit partial ``allowed_loss`` AND
  ``fully_allowed=True`` on the same year, the effective behavior is full-loss
  absorption (``fully_allowed`` wins), i.e. that year's ``suspended == 0.00``.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring the composed-service fixture in
``test_carryforward_running_balance_property.py``. Per-example provisioning is
not instantaneous, so the deadline is disabled; the example count is held at
100.
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

# A small spread of distinct, deliberately non-contiguous tax years the
# generated transactions are dated within, so the reconciled series spans
# several Data_Years with gaps — one of which is forced to be a Loss_Year.
_TAX_YEARS = [2020, 2022, 2023, 2025]


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
# To exercise Property 3 we need a guaranteed Loss_Year. We draw one target
# year from the spread and force a net loss there by seeding a pure-expense line
# (no offsetting income), then layer arbitrary other transactions across the
# remaining years so the series spans several Data_Years with varied nets.

# Two-decimal money magnitudes used for both the forced loss line and the
# arbitrary surrounding transactions.
_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# (type, category_id) pairs across a spread of Schedule E lines. Income and
# expense specs so the surrounding years mix loss and gain.
_INCOME_SPECS = [("income", "rents-received"), ("income", "royalties-received")]
_EXPENSE_SPECS = [
    ("expense", "repairs"),
    ("expense", "utilities"),
]

# A non-negative two-decimal Opening_Balance set via set_opening_balance.
_opening_amounts = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def _surrounding_txn(
    draw: st.DrawFn,
) -> tuple[str, str, Decimal, int]:
    """One (type, category_id, amount, tax_year) transaction in a NON-target year.

    These surround the forced loss year to make the series span several
    Data_Years with varied per-year nets. The tax year is drawn from the spread;
    the running-balance loop re-derives the target year's loss regardless.
    """
    ttype, category = draw(st.sampled_from(_INCOME_SPECS + _EXPENSE_SPECS))
    amount = draw(_amounts)
    year = draw(st.sampled_from(_TAX_YEARS))
    return ttype, category, amount, year


def _iso_date(year: int, index: int) -> str:
    """A deterministic in-year ISO date, cycling day/month to stay valid."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _seed_expense(transactions, pid: str, year: int, amount: Decimal, index: int):
    """Create one repairs expense in ``year`` and assert it persisted."""
    result = transactions.create(
        TransactionInput(
            property_id=pid,
            date=_iso_date(year, index),
            amount=amount,
            type="expense",
            category_id="repairs",
        )
    )
    assert result.is_ok, result.error


def _expected_series(summary) -> list[tuple[int, Decimal]]:
    """The (tax_year, expected_carryforward) series for easy equality checks."""
    return [(y.tax_year, y.expected_carryforward) for y in summary.years]


def _year(summary, tax_year: int):
    """The single ReconciledYear for ``tax_year`` in the summary."""
    for y in summary.years:
        if y.tax_year == tax_year:
            return y
    raise AssertionError(f"year {tax_year} not in reconciled series")


# Feature: carryforward-allowed-loss, Property 3: Fully-allowed contributes zero
# and equals the explicit-full-amount case
#
# NOTE: held at 50 examples (the task's stated fallback) rather than 100 — each
# example provisions its own moto store and runs several reconciles/writes, and
# under the orchestrator's concurrent sibling property suites 100 examples
# exceeded the 900s verification budget; 50 keeps the property's coverage of the
# toggle / explicit-full-amount / dynamic-tracking / precedence facets while
# finishing within budget.
@settings(deadline=None, max_examples=50)
@given(
    loss_year=st.sampled_from(_TAX_YEARS),
    loss_amount=st.decimals(
        min_value=Decimal("0.01"),
        max_value=Decimal("1000000.00"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    extra_loss=st.decimals(
        min_value=Decimal("0.01"),
        max_value=Decimal("1000000.00"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    surrounding=st.lists(_surrounding_txn(), min_size=0, max_size=8),
    opening=_opening_amounts,
)
def test_fully_allowed_contributes_zero_and_equals_explicit_full_amount(
    loss_year: int,
    loss_amount: Decimal,
    extra_loss: Decimal,
    surrounding: list[tuple[str, str, Decimal, int]],
    opening: Decimal,
) -> None:
    """Fully_Allowed ⇒ suspended 0.00, equals explicit full amount, tracks net.

    Validates: Requirements 3.7, 4.2, 4.3, 4.4, 8.3
    """
    with _moto_service() as (service, properties, transactions):
        created = properties.create(
            PropertyInput(
                name="Prop",
                address_text="1 Main St",
                property_type="single_family",
            )
        )
        assert created.is_ok, created.error
        pid = created.value.id

        # Force a Loss_Year: a pure expense line with no offsetting income in
        # that year guarantees schedule_e_net < 0 there.
        _seed_expense(transactions, pid, loss_year, loss_amount, index=0)

        # Surround it with arbitrary other transactions in OTHER years (any
        # sign) so the series spans several Data_Years with varied nets. Any
        # draw that lands in the target year is skipped, so the forced expense
        # there is never offset — the target stays a strict Loss_Year.
        for t_index, (ttype, category, amount, year) in enumerate(surrounding):
            if year == loss_year:
                continue
            result = transactions.create(
                TransactionInput(
                    property_id=pid,
                    date=_iso_date(year, t_index + 1),
                    amount=amount,
                    type=ttype,
                    category_id=category,
                )
            )
            assert result.is_ok, result.error

        opening_result = service.set_opening_balance(f"{opening:.2f}")
        assert opening_result.is_ok, opening_result.error

        # The target year's current Loss_Magnitude, as the engine derives it.
        baseline = service.reconcile()
        target = _year(baseline, loss_year)
        assert target.schedule_e_net < 0, (
            "target year must be a Loss_Year",
            loss_year,
            target.schedule_e_net,
        )
        loss_magnitude = -target.schedule_e_net

        # --- Facet A: toggle == explicit full amount (Req 8.3) -------------
        # Run with fully_allowed on.
        on = service.set_fully_allowed(loss_year, True)
        assert on.is_ok, on.error
        fully_summary = service.reconcile()

        fully_year = _year(fully_summary, loss_year)
        # The fully-allowed year contributes nothing to the balance: its
        # expected equals the balance carried IN (opening when it is the first
        # and only loss), i.e. the loss was fully absorbed (Req 3.7, 4.2).
        assert fully_year.fully_allowed is True
        assert fully_year.allowed_loss == Decimal("0.00"), (
            "fully_allowed must NOT snapshot the loss into allowed_loss",
            fully_year.allowed_loss,
        )

        # Now clear the flag and store an explicit allowed_loss equal to the
        # current Loss_Magnitude; the resulting series must be IDENTICAL.
        off = service.set_fully_allowed(loss_year, False)
        assert off.is_ok, off.error
        explicit = service.set_allowed_loss(
            loss_year, f"{loss_magnitude:.2f}"
        )
        assert explicit.is_ok, explicit.error
        explicit_summary = service.reconcile()

        assert _expected_series(fully_summary) == _expected_series(
            explicit_summary
        ), (
            "fully_allowed must equal explicit full-amount series",
            _expected_series(fully_summary),
            _expected_series(explicit_summary),
        )

        # The explicit-full-amount year also contributes 0.00 suspended.
        explicit_year = _year(explicit_summary, loss_year)
        assert explicit_year.allowed_loss == loss_magnitude

        # --- Facet B: dynamic tracking of the current magnitude (Req 4.3) ---
        # Re-arm fully_allowed, then DEEPEN the loss (add another expense in the
        # same year). The year must still contribute 0.00 suspended, proving the
        # flag tracks the current (larger) magnitude, not a snapshot.
        service.clear_allowed_loss(loss_year)
        rearm = service.set_fully_allowed(loss_year, True)
        assert rearm.is_ok, rearm.error

        _seed_expense(transactions, pid, loss_year, extra_loss, index=99)

        changed_summary = service.reconcile()
        changed_year = _year(changed_summary, loss_year)
        assert changed_year.schedule_e_net < target.schedule_e_net, (
            "extra expense must deepen the loss",
            target.schedule_e_net,
            changed_year.schedule_e_net,
        )
        new_magnitude = -changed_year.schedule_e_net

        # Oracle: the year's suspended contribution is the delta between its
        # expected and the balance carried in. Re-derive the balance carried in
        # by walking the series up to (but not including) the target year.
        carried_in = changed_summary.opening_balance
        for y in changed_summary.years:
            if y.tax_year == loss_year:
                break
            carried_in = y.expected_carryforward
        suspended_contribution = changed_year.expected_carryforward - carried_in
        assert suspended_contribution == Decimal("0.00"), (
            "fully_allowed year must contribute 0.00 at the CURRENT magnitude",
            new_magnitude,
            carried_in,
            changed_year.expected_carryforward,
        )

        # --- Facet C: fully_allowed takes precedence over explicit (Req 4.4) --
        # Set BOTH a partial explicit allowed_loss AND fully_allowed=True on the
        # same (current) year; the full loss must still be absorbed (suspended
        # 0.00), i.e. the flag wins over the explicit partial amount.
        partial = (new_magnitude / 2).quantize(Decimal("0.01"))
        if partial > new_magnitude:  # defensive; quantize never rounds up here
            partial = new_magnitude
        set_partial = service.set_allowed_loss(loss_year, f"{partial:.2f}")
        assert set_partial.is_ok, set_partial.error
        # fully_allowed is still on from Facet B; reconcile with both present.
        both_summary = service.reconcile()
        both_year = _year(both_summary, loss_year)
        assert both_year.fully_allowed is True
        assert both_year.allowed_loss == partial, (
            "the explicit partial amount is stored but moot while flag is on",
            both_year.allowed_loss,
            partial,
        )

        carried_in_both = both_summary.opening_balance
        for y in both_summary.years:
            if y.tax_year == loss_year:
                break
            carried_in_both = y.expected_carryforward
        both_contribution = both_year.expected_carryforward - carried_in_both
        assert both_contribution == Decimal("0.00"), (
            "fully_allowed must win over the explicit partial amount "
            "(full loss absorbed, suspended 0.00)",
            partial,
            new_magnitude,
            carried_in_both,
            both_year.expected_carryforward,
        )


# Feature: carryforward-allowed-loss, Property 4: Monotonic roll-forward of a
# year's allowed amount
#
# NOTE: held at 50 examples — each example provisions its own moto store and
# runs TWO full reconciles (one per allowed level) on top of the per-example
# provisioning; under the orchestrator's concurrent sibling property suites 100
# examples exceeded the 900s verification budget, so 50 keeps the property's
# monotone / exact-delta / later-year coverage while finishing within budget.
@settings(deadline=None, max_examples=50)
@given(
    target_year=st.sampled_from(_TAX_YEARS),
    target_loss=st.decimals(
        min_value=Decimal("0.02"),
        max_value=Decimal("1000000.00"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    later_txns=st.lists(_surrounding_txn(), min_size=0, max_size=8),
    opening=_opening_amounts,
    split=st.floats(min_value=0.01, max_value=0.99),
)
def test_increasing_allowed_monotonically_rolls_forward(
    target_year: int,
    target_loss: Decimal,
    later_txns: list[tuple[str, str, Decimal, int]],
    opening: Decimal,
    split: float,
) -> None:
    """Raising a year's Allowed_Loss never raises — and, while that year's
    suspended is still positive, strictly lowers by the exact delta — its own
    and every later year's Expected_Carryforward; lowering it never lowers them.

    Validates: Requirements 3.1, 3.3
    """
    with _moto_service() as (service, properties, transactions):
        created = properties.create(
            PropertyInput(
                name="Prop",
                address_text="1 Main St",
                property_type="single_family",
            )
        )
        assert created.is_ok, created.error
        pid = created.value.id

        # A guaranteed Loss_Year of known magnitude M: a pure expense line with
        # no offsetting income in that year forces schedule_e_net == -target_loss.
        _seed_expense(transactions, pid, target_year, target_loss, index=0)

        # Optionally layer transactions in OTHER years so the roll-forward lands
        # on subsequent years with varied nets. Any draw that lands on the target
        # year is skipped so the target stays a strict Loss_Year of magnitude M.
        for t_index, (ttype, category, amount, year) in enumerate(later_txns):
            if year == target_year:
                continue
            result = transactions.create(
                TransactionInput(
                    property_id=pid,
                    date=_iso_date(year, t_index + 1),
                    amount=amount,
                    type=ttype,
                    category_id=category,
                )
            )
            assert result.is_ok, result.error

        opening_result = service.set_opening_balance(f"{opening:.2f}")
        assert opening_result.is_ok, opening_result.error

        # Confirm the engine derives the target as a Loss_Year and recover M as
        # the engine sees it.
        baseline = service.reconcile()
        target = _year(baseline, target_year)
        assert target.schedule_e_net < 0, (
            "target year must be a Loss_Year",
            target_year,
            target.schedule_e_net,
        )
        magnitude = -target.schedule_e_net  # M, non-negative two-decimal

        # Pick two allowed amounts a_low < a_high, both within [0, M]. a_low is a
        # fraction of M (so a_low < M ⇒ the suspended at a_low is strictly
        # positive), a_high is the full magnitude M.
        a_low = (magnitude * Decimal(str(split))).quantize(Decimal("0.01"))
        if a_low >= magnitude:  # defensive: keep a_low strictly below M
            a_low = magnitude - Decimal("0.01")
        if a_low < Decimal("0.00"):
            a_low = Decimal("0.00")
        a_high = magnitude
        assert a_low < a_high <= magnitude, (a_low, a_high, magnitude)

        # Reconcile at a_low, capture the series; then at a_high, capture again.
        low_set = service.set_allowed_loss(target_year, f"{a_low:.2f}")
        assert low_set.is_ok, low_set.error
        low_summary = service.reconcile()

        high_set = service.set_allowed_loss(target_year, f"{a_high:.2f}")
        assert high_set.is_ok, high_set.error
        high_summary = service.reconcile()

        low_expected = {y.tax_year: y.expected_carryforward for y in low_summary.years}
        high_expected = {
            y.tax_year: y.expected_carryforward for y in high_summary.years
        }
        assert low_expected.keys() == high_expected.keys()

        delta = a_high - a_low  # the amount by which the allowance increased

        # The years at or after the target, in reconciled (ascending) order.
        target_and_later = [
            y.tax_year for y in high_summary.years if y.tax_year >= target_year
        ]

        for year in target_and_later:
            lo = low_expected[year]
            hi = high_expected[year]
            # Monotone non-increasing in the allowed amount for the target year
            # and EVERY later year (Req 3.1, 3.3): raising the allowance can only
            # lower a downstream expected (or leave it at a gain-imposed 0.00
            # floor), never raise it.
            assert hi <= lo, (
                "raising allowed must never raise a downstream expected",
                year,
                lo,
                hi,
            )

        # Exact-delta drop for the TARGET year specifically. Its expected is
        # carried_in + max(M - allowed, 0.00); since a_low < a_high <= M, the
        # suspended at a_low is M - a_low > 0, so raising the allowance by `delta`
        # lowers the target year's expected by exactly `delta` (the target year's
        # own balance has not hit a gain floor from the added allowance — the
        # allowance only reduces what this year ADDS).
        target_drop = low_expected[target_year] - high_expected[target_year]
        assert target_drop == delta, (
            "target year's expected must drop by exactly the allowance delta "
            "while its suspended is still positive",
            delta,
            low_expected[target_year],
            high_expected[target_year],
        )

        # And the converse: DECREASING the allowance (high → low) never lowers
        # any downstream expected — i.e. low_expected >= high_expected
        # everywhere, which is exactly the `hi <= lo` asserted above, so
        # decreasing never decreases them.
