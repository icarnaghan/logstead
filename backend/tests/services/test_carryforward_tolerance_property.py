"""Property-based tests for the tolerant carryforward status comparison.

These tests exercise ``CarryforwardService.reconcile()`` against an independent
oracle written in integer cents (exact ``Decimal`` at the boundary, no float).
The flow per example:

1. Seed a property with random income/expense transactions and an opening
   balance, then reconcile once to learn each year's Schedule E net.
2. Walk the series with the oracle, tracking the expected carry-in and the
   chain value (the previous *reported* figure pushed through the previous
   year's step), and choose each reported value as the expected or chain value
   plus a signed offset in cents.
3. Set the reported values, reconcile again, and compare the statuses with the
   oracle's four-rule precedence using ``STATUS_TOLERANCE``.

Layout: shared helpers and strategies come first so further properties can be
appended below. Each Hypothesis example provisions its own moto-backed
single-table DynamoDB (base + GSI1 + GSI2) plus an S3 bucket, composing the
real service stack, mirroring
``test_carryforward_chain_status_compat_property.py``.
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

_TAX_YEARS = [2020, 2022, 2023, 2025]

_CENTS = Decimal("0.01")
_TOL_CENTS = int(STATUS_TOLERANCE / _CENTS)  # 200


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

_opening_amounts = st.decimals(
    min_value=Decimal("0.00"),
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

# Signed offsets in cents.
_within_offsets = st.one_of(
    st.integers(min_value=-_TOL_CENTS, max_value=_TOL_CENTS),
    st.sampled_from([-_TOL_CENTS, _TOL_CENTS, 0]),
)
_just_outside_offsets = st.sampled_from([-(_TOL_CENTS + 1), _TOL_CENTS + 1])
_mixed_offsets = st.one_of(
    _within_offsets,
    _just_outside_offsets,
    st.integers(min_value=-1000, max_value=1000),
)

# A year's plan: skip it, or base on the expected carry-in / the chain value
# plus a signed offset in cents.
_BASES = ["unreported", "expected", "chain"]


def _plan(offsets: st.SearchStrategy[int]):
    return st.lists(
        st.tuples(st.sampled_from(_BASES), offsets),
        min_size=len(_TAX_YEARS),
        max_size=len(_TAX_YEARS),
    )


# --- Helpers ------------------------------------------------------------------
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


def _cents(value: Decimal) -> int:
    """Exact integer cents of a two-decimal Decimal."""
    return int((value / _CENTS).to_integral_value())


def _step(balance: int, net: int) -> int:
    """One year's carry-out in cents (no allowed loss set in these tests)."""
    return balance + (-net) if net < 0 else max(balance - net, 0)


class _Row:
    """Oracle view of one year: inputs chosen and the expected classification."""

    net: int = 0  # Schedule E net in cents, set by ``_run``

    def __init__(
        self,
        year: int,
        expected_in: int,
        chain_in: int | None,
        reported: int | None,
        base: str,
        offset: int,
    ) -> None:
        self.year = year
        self.expected_in = expected_in
        self.chain_in = chain_in
        self.reported = reported
        self.base = base
        self.offset = offset

    @property
    def status(self) -> str:
        """Independent four-rule precedence in integer cents."""
        if self.reported is None:
            return "unreported"
        if abs(self.reported - self.expected_in) <= _TOL_CENTS:
            return "ok"
        if self.chain_in is not None and abs(self.reported - self.chain_in) <= _TOL_CENTS:
            return "carried"
        return "mismatch"


def _run(properties_txns, opening, plan):
    """Seed, reconcile, set reported values per plan, reconcile again.

    Returns ``(rows, summary)`` where ``rows`` is the oracle's per-year view
    (parallel to ``summary.years``) built from the first reconcile's nets and
    the reported values actually set.
    """
    with _moto_service() as (service, properties, transactions):
        _seed(service, properties, transactions, properties_txns, opening)

        first = service.reconcile()
        balance = _cents(first.opening_balance)
        prev_reported: int | None = None
        prev_net: int | None = None
        rows: list[_Row] = []
        for index, year in enumerate(first.years):
            net = _cents(year.schedule_e_net)
            base, offset = plan[index] if index < len(plan) else ("unreported", 0)
            expected_in = balance
            chain_in = (
                _step(prev_reported, prev_net)
                if index > 0 and prev_reported is not None and prev_net is not None
                else None
            )
            reported: int | None = None
            if base != "unreported":
                anchor = expected_in
                if base == "chain" and chain_in is not None:
                    anchor = chain_in
                reported = max(anchor + offset, 0)
                res = service.set_reported(
                    year.tax_year, f"{Decimal(reported) * _CENTS:.2f}"
                )
                assert res.is_ok, (year.tax_year, res.error)
            row = _Row(year.tax_year, expected_in, chain_in, reported, base, offset)
            row.net = net
            rows.append(row)
            balance = _step(expected_in, net)
            prev_reported, prev_net = reported, net

        summary = service.reconcile()
        assert len(summary.years) == len(rows)
        return rows, summary


def _assert_matches_oracle(rows, summary) -> None:
    for row, year in zip(rows, summary.years):
        assert year.tax_year == row.year
        assert _cents(year.expected_carry_in) == row.expected_in, row.year
        assert year.status == row.status, (
            row.year,
            year.status,
            row.status,
            row.reported,
            row.expected_in,
            row.chain_in,
        )


# Feature: carryforward-tolerance-and-year-range, Property 1: Status follows
# the tolerant four-rule precedence
@settings(deadline=None, max_examples=100)
@given(
    properties_txns=st.lists(_property_txns, min_size=1, max_size=3),
    opening=_opening_amounts,
    plan=_plan(_mixed_offsets),
)
def test_status_follows_tolerant_precedence(
    properties_txns: list[list[tuple[str, str, Decimal, str | None, int]]],
    opening: Decimal,
    plan: list[tuple[str, int]],
) -> None:
    """Every year's status equals the independent cents oracle.

    Validates: Requirements 1.2, 1.3, 1.4, 1.5, 1.6, 2.7, 2.8
    """
    rows, summary = _run(properties_txns, opening, plan)
    _assert_matches_oracle(rows, summary)


# Feature: carryforward-tolerance-and-year-range, Property 2: Values within
# tolerance classify as ok or carried
@settings(deadline=None, max_examples=100)
@given(
    properties_txns=st.lists(_property_txns, min_size=1, max_size=3),
    opening=_opening_amounts,
    plan=_plan(_within_offsets),
)
def test_values_within_tolerance_are_ok_or_carried(
    properties_txns: list[list[tuple[str, str, Decimal, str | None, int]]],
    opening: Decimal,
    plan: list[tuple[str, int]],
) -> None:
    """Expected +/- <=2.00 is ok; chain +/- <=2.00 (not near expected) is carried.

    Validates: Requirements 1.2, 1.3, 1.9, 2.3
    """
    rows, summary = _run(properties_txns, opening, plan)
    _assert_matches_oracle(rows, summary)
    for row, year in zip(rows, summary.years):
        if row.reported is None:
            continue
        if row.base == "expected" or (row.base == "chain" and row.chain_in is None):
            # Anchored on expected (flooring at 0 only moves toward it).
            assert year.status == "ok", (row.year, year.status)
        elif abs(row.reported - row.expected_in) > _TOL_CENTS:
            assert year.status == "carried", (row.year, year.status)
        else:
            assert year.status == "ok", (row.year, year.status)


# Feature: carryforward-tolerance-and-year-range, Property 3: Values just
# outside tolerance classify as mismatch
@settings(deadline=None, max_examples=100)
@given(
    properties_txns=st.lists(_property_txns, min_size=1, max_size=3),
    opening=_opening_amounts,
    plan=_plan(_just_outside_offsets),
)
def test_values_just_outside_tolerance_are_mismatch(
    properties_txns: list[list[tuple[str, str, Decimal, str | None, int]]],
    opening: Decimal,
    plan: list[tuple[str, int]],
) -> None:
    """A value >=2.01 from both the expected carry-in and chain is mismatch.

    Validates: Requirements 1.4, 1.10
    """
    rows, summary = _run(properties_txns, opening, plan)
    _assert_matches_oracle(rows, summary)
    for row, year in zip(rows, summary.years):
        if row.reported is None:
            continue
        far_from_expected = abs(row.reported - row.expected_in) > _TOL_CENTS
        far_from_chain = (
            row.chain_in is None or abs(row.reported - row.chain_in) > _TOL_CENTS
        )
        if far_from_expected and far_from_chain:
            assert year.status == "mismatch", (row.year, year.status)


_Txns = list[list[tuple[str, str, Decimal, str | None, int]]]


# Feature: carryforward-tolerance-and-year-range, Property 4: Tolerance never
# changes values, drift or attribution inputs
@settings(deadline=None, max_examples=100)
@given(
    properties_txns=st.lists(_property_txns, min_size=1, max_size=3),
    opening=_opening_amounts,
    plan=_plan(_mixed_offsets),
)
def test_tolerance_never_changes_values_or_drift(
    properties_txns: _Txns,
    opening: Decimal,
    plan: list[tuple[str, int]],
) -> None:
    """Expected values follow the exact recurrence; drift is exact reported - expected.

    Validates: Requirements 2.1, 2.2, 2.3, 2.4
    """
    rows, summary = _run(properties_txns, opening, plan)
    balance = _cents(summary.opening_balance)
    for row, year in zip(rows, summary.years):
        assert _cents(year.expected_carry_in) == balance == row.expected_in
        expected_out = _step(balance, row.net)
        assert year.expected_carryforward == Decimal(expected_out) * _CENTS
        if row.reported is None:
            assert year.reported_carryforward is None
            assert year.drift is None
        else:
            assert year.reported_carryforward == Decimal(row.reported) * _CENTS
            # Exact to the cent, whatever the status (ok years may be non-zero).
            assert year.drift == Decimal(row.reported - row.expected_in) * _CENTS
        balance = expected_out
    assert _cents(summary.next_year_expected_carry_in) == balance


# Feature: carryforward-tolerance-and-year-range, Property 5: Root-cause
# attribution is unchanged
@settings(deadline=None, max_examples=100)
@given(
    properties_txns=st.lists(_property_txns, min_size=1, max_size=3),
    opening=_opening_amounts,
    plan=_plan(_mixed_offsets),
)
def test_root_cause_attribution_unchanged(
    properties_txns: _Txns,
    opening: Decimal,
    plan: list[tuple[str, int]],
) -> None:
    """carried_from_year is the latest earlier mismatch year; never an ok year.

    Validates: Requirements 2.5, 2.6
    """
    rows, summary = _run(properties_txns, opening, plan)
    last_mismatch: int | None = None
    for row, year in zip(rows, summary.years):
        assert year.status == row.status
        if year.status == "carried":
            assert year.carried_from_year == last_mismatch
            if year.carried_from_year is not None:
                assert year.carried_from_year < year.tax_year
                source = next(r for r in rows if r.year == year.carried_from_year)
                assert source.status == "mismatch"
        else:
            assert year.carried_from_year is None
        if year.status == "mismatch":
            last_mismatch = year.tax_year


# Feature: carryforward-tolerance-and-year-range, Property 6: Backward
# compatibility of exact matches
_exact_plan = st.lists(
    st.tuples(st.sampled_from(_BASES), st.just(0)),
    min_size=len(_TAX_YEARS),
    max_size=len(_TAX_YEARS),
)


@settings(deadline=None, max_examples=100)
@given(
    properties_txns=st.lists(_property_txns, min_size=1, max_size=3),
    opening=_opening_amounts,
    plan=_exact_plan,
)
def test_exact_matches_keep_their_pre_feature_status(
    properties_txns: _Txns,
    opening: Decimal,
    plan: list[tuple[str, int]],
) -> None:
    """Exact-equal years stay ok, exact chain years stay carried, unreported stays.

    Validates: Requirements 3.1, 3.2, 3.3, 3.4
    """
    rows, summary = _run(properties_txns, opening, plan)
    _assert_matches_oracle(rows, summary)
    for row, year in zip(rows, summary.years):
        if row.reported is None:
            assert year.status == "unreported"
            assert year.drift is None
            assert year.carried_from_year is None
        elif row.reported == row.expected_in:
            assert year.status == "ok"
            assert year.drift == Decimal("0.00")
        elif row.chain_in is not None and row.reported == row.chain_in:
            # Exactly carried and not within tolerance of expected: still carried.
            if abs(row.reported - row.expected_in) > _TOL_CENTS:
                assert year.status == "carried"


# Feature: carryforward-tolerance-and-year-range, Property 7: Real-data shape
# yields carried
_REAL_YEARS = [2019, 2020, 2022, 2023, 2024, 2025]


@settings(deadline=None, max_examples=100)
@given(
    losses=st.lists(
        st.decimals(
            min_value=Decimal("100.00"),
            max_value=Decimal("100000.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=len(_REAL_YEARS),
        max_size=len(_REAL_YEARS),
    ),
    opening=_opening_amounts,
    root_index=st.integers(min_value=0, max_value=2),
    # Root-cause error: at least $100 above expected, far outside tolerance.
    root_error=st.integers(min_value=10_000, max_value=500_000),
    # "A few dollars or cents" from the chain value, including the 2.00 edge.
    offsets=st.lists(
        st.integers(min_value=-_TOL_CENTS, max_value=_TOL_CENTS),
        min_size=len(_REAL_YEARS),
        max_size=len(_REAL_YEARS),
    ),
)
def test_real_data_shape_yields_carried(
    losses: list[Decimal],
    opening: Decimal,
    root_index: int,
    root_error: int,
    offsets: list[int],
) -> None:
    """After a root-cause mismatch every later chain-plus-dollars year is carried.

    Each year has only an expense, so the year's step never floors at zero and
    the reported-minus-expected gap stays near the root error (it moves by at
    most 2.00 per later year, far less than the 100.00 minimum error).

    Validates: Requirements 1.3, 1.7, 2.5
    """
    txns = [
        [
            ("expense", "repairs", loss, None, year)
            for year, loss in zip(_REAL_YEARS, losses)
        ]
    ]
    plan: list[tuple[str, int]] = []
    for index in range(len(_REAL_YEARS)):
        if index < root_index:
            plan.append(("expected", 0))
        elif index == root_index:
            plan.append(("expected", root_error))
        else:
            plan.append(("chain", offsets[index]))

    rows, summary = _run(txns, opening, plan)
    assert [y.tax_year for y in summary.years] == _REAL_YEARS
    root_year = _REAL_YEARS[root_index]
    for index, year in enumerate(summary.years):
        if index < root_index:
            assert year.status == "ok", (year.tax_year, year.status)
        elif index == root_index:
            assert year.status == "mismatch", (year.tax_year, year.status)
            assert year.carried_from_year is None
        else:
            assert abs(rows[index].reported - rows[index].expected_in) > _TOL_CENTS
            assert year.status == "carried", (year.tax_year, year.status)
            assert year.carried_from_year == root_year
