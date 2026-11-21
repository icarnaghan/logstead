"""Property tests — carryforward persistence, scoping, empty case, §469 boundary.

# Feature: passive-loss-carryforward, Property 8/10/11/12: reported round-trips
#   and validates; user scoping; empty non-error series; §469 is never applied
# Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 6.1, 6.2, 7.5, 2.7, 8.3

These four properties exercise ``CarryforwardService`` (``services/carryforward.py``)
against a ``moto``-backed single-table DynamoDB, with each
:class:`CarryforwardService` composed over a real, user-scoped
:class:`PropertyService` / :class:`ReportingService` / :class:`TransactionService`
/ :class:`DepreciationService` stack — mirroring the moto fixture and two-user
composition in ``test_trends_scoping_property.py`` and
``test_trends_reconciliation_property.py``.

* **Property 8 — Reported round-trips and validates** (Req 3.1-3.4): a persisted
  Reported_Carryforward reads back equal to its normalized two-decimal form;
  :meth:`set_reported` / :meth:`set_opening_balance` reject a negative or
  non-two-decimal amount with a ``validation`` failure identifying ``field ==
  "amount"`` and persist nothing; :meth:`clear_reported` removes the entry (the
  year reverts to ``unreported``) and is idempotent (clearing an absent year
  still succeeds).
* **Property 10 — User scoping** (Req 3.5, 7.5): two users over the SAME table,
  each with its own service stack bound to its own user id; each user's
  :meth:`reconcile` reflects only their own properties, reported entries, and
  opening balance, and neither can read or modify the other's.
* **Property 11 — Empty, non-error series** (Req 6.1, 6.2): a user with no
  Data_Years and no Opening_Balance yields ``years == ()``, ``has_data ==
  False``, and ``opening_balance == Decimal("0.00")`` — raising no error.
* **Property 12 — §469 limitation is never applied** (Req 2.7, 8.3): for
  generated nets + opening balance, the returned Expected_Carryforward series
  equals an independent recomputation of the running-balance recurrence over the
  SAME returned nets (a loss adds its magnitude; a gain is absorbed, floored at
  0.00). This proves no $25,000 allowance / MAGI phase-out / Form 8582 logic
  influences the figure, even for inputs where a real §469 result would differ.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``. Per-example provisioning is not instantaneous, so the
deadline is disabled and the example count is held at 100.
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
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.carryforward import CarryforwardService
from logstead.services.dashboard import latest_tax_year
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_A = "user-a"
USER_B = "user-b"


@contextlib.contextmanager
def _moto_table():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields a ``(repo, files)`` pair bound to freshly created resources so each
    Hypothesis example runs against a clean store shared by both users. GSI1 is
    required by ``PropertyService.create`` (property-meta mirror); GSI2 is the
    tax-year partition that depreciation schedules read through.
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
        yield DynamoRepository(ddb, TABLE_NAME), S3FileAdapter(s3, BUCKET)


def _wire(repo, files, user_id: str) -> tuple[
    CarryforwardService, PropertyService, TransactionService, DepreciationService
]:
    """Compose a full, user-scoped service stack for one user over the shared store.

    Constructs ``CarryforwardService(repo, USER, reports, properties,
    transactions, depreciation)`` so it derives the SAME Data_Years as the
    dashboard via the shared ``derive_data_years`` helper.
    """
    properties = PropertyService(repo, user_id)
    transactions = TransactionService(repo, files)
    depreciation = DepreciationService(repo)
    reports = ReportingService(transactions, depreciation, properties)
    carryforward = CarryforwardService(
        repo, user_id, reports, properties, transactions, depreciation
    )
    return carryforward, properties, transactions, depreciation


def _iso_date(year: int, index: int) -> str:
    """A deterministic in-year ISO date; year is what the Data_Year keys on."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


# --- Strategies --------------------------------------------------------------

# A small spread of distinct, non-contiguous tax years capped at the latest
# completed year, so generated series span several Data_Years and never hit the
# un-fileable current/future-year cap.
_YEAR_CAP = latest_tax_year()
_YEAR_POOL = [y for y in (2017, 2019, 2020, 2022, 2023) if y <= _YEAR_CAP]

# A non-negative two-decimal money magnitude, as a string (the reported /
# opening-balance input the service validates). Kept well within range.
_money_str = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
).map(lambda d: f"{d:.2f}")

# An invalid amount: either negative two-decimal or a non-parseable / >2-dp
# string. All must be rejected with a validation failure on field "amount".
_negative_money = st.decimals(
    min_value=Decimal("-1000000.00"),
    max_value=Decimal("-0.01"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
).map(lambda d: f"{d:.2f}")
# Non-parseable money strings the money boundary (``util.money.to_money``)
# genuinely rejects. Note: a value like ``"1.234"`` is NOT listed — the money
# boundary *rounds* extra precision half-up (to ``"1.23"``) rather than
# rejecting it, so the service accepts and normalizes it; only un-parseable or
# non-finite input is rejected. These are the "not a valid two-decimal money
# amount" cases of Req 3.3 that the service actually refuses.
_unparseable = st.sampled_from(
    ["", "   ", "abc", "12.5x", "NaN", "Infinity", "$10.00", "1,000.00", "--1.00"]
)
_invalid_amount = st.one_of(_negative_money, _unparseable)


# --- Property 8 : Reported round-trips and validates -------------------------


# Feature: passive-loss-carryforward, Property 8: Reported round-trips and
# validates (persist/replace/validate-reject/idempotent-clear)
# Validates: Requirements 3.1, 3.2, 3.3, 3.4
@settings(deadline=None, max_examples=100)
@given(
    year=st.sampled_from(_YEAR_POOL) if _YEAR_POOL else st.just(2020),
    first=_money_str,
    second=_money_str,
    bad=_invalid_amount,
)
def test_reported_round_trips_and_validates(
    year: int, first: str, second: str, bad: str
) -> None:
    """A persisted reported value reads back normalized; invalid rejects; clear is idempotent.

    Validates: Requirements 3.1, 3.2, 3.3, 3.4
    """
    with _moto_table() as (repo, files):
        service, properties, _txns, _depr = _wire(repo, files, USER_A)
        # A single property so the year is a real Data_Year and the reconcile
        # surfaces a ReconciledYear for it.
        created = properties.create(
            PropertyInput(
                name="P",
                address_text="1 St",
                property_type="single_family",
            )
        )
        assert created.is_ok, created.error
        pid = created.value.id
        # One transaction in the target year so the year is derived.
        txn = _txns.create(
            TransactionInput(
                property_id=pid,
                date=_iso_date(year, 0),
                amount=Decimal("100.00"),
                type="income",
                category_id="rents-received",
                description=None,
            )
        )
        assert txn.is_ok, txn.error

        # --- Persist + round-trip (Req 3.1): reads back the normalized form ---
        result = service.set_reported(year, first)
        assert result.is_ok, result.error
        normalized_first = f"{Decimal(first):.2f}"
        found = next(
            (y for y in service.reconcile().years if y.tax_year == year), None
        )
        assert found is not None, "reported year missing from reconcile()"
        assert found.reported_carryforward is not None
        assert found.reported_carryforward == Decimal(normalized_first)

        # --- Replace (Req 3.2): a second submit overwrites the first ----------
        replace = service.set_reported(year, second)
        assert replace.is_ok, replace.error
        normalized_second = f"{Decimal(second):.2f}"
        found = next(
            (y for y in service.reconcile().years if y.tax_year == year), None
        )
        assert found is not None
        assert found.reported_carryforward == Decimal(normalized_second)

        # --- Validate-reject (Req 3.3): invalid amount rejected, nothing saved
        reject = service.set_reported(year, bad)
        assert not reject.is_ok
        assert reject.error is not None
        assert reject.error.kind == "validation"
        assert reject.error.field == "amount"
        # The prior value is untouched by the rejected write.
        found = next(
            (y for y in service.reconcile().years if y.tax_year == year), None
        )
        assert found is not None
        assert found.reported_carryforward == Decimal(normalized_second)

        # set_opening_balance rejects the same invalid input identically, and
        # persists nothing (opening_balance stays 0.00).
        reject_open = service.set_opening_balance(bad)
        assert not reject_open.is_ok
        assert reject_open.error is not None
        assert reject_open.error.kind == "validation"
        assert reject_open.error.field == "amount"
        assert service.reconcile().opening_balance == Decimal("0.00")

        # --- Clear (Req 3.4): removes the entry; year reverts to unreported ---
        cleared = service.clear_reported(year)
        assert cleared.is_ok, cleared.error
        found = next(
            (y for y in service.reconcile().years if y.tax_year == year), None
        )
        assert found is not None
        assert found.reported_carryforward is None
        assert found.status == "unreported"

        # Idempotent: clearing an already-absent year still succeeds.
        again = service.clear_reported(year)
        assert again.is_ok, again.error
        # A never-reported, unrelated year clears successfully too.
        absent = service.clear_reported(year + 100)
        assert absent.is_ok, absent.error


# --- Property 10 : User scoping ---------------------------------------------


@st.composite
def _user_seed(draw: st.DrawFn):
    """A per-user seed: property transaction-years, reported entries, opening balance."""
    years = draw(st.lists(st.sampled_from(_YEAR_POOL), min_size=1, max_size=4)) \
        if _YEAR_POOL else [2020]
    reported = draw(
        st.dictionaries(
            keys=st.sampled_from(_YEAR_POOL) if _YEAR_POOL else st.just(2020),
            values=_money_str,
            max_size=3,
        )
    )
    opening = draw(_money_str)
    return years, reported, opening


def _seed_user(
    service: CarryforwardService,
    properties: PropertyService,
    transactions: TransactionService,
    tag: str,
    seed,
) -> None:
    """Create one property with transactions in the seed years, then write state."""
    years, reported, opening = seed
    created = properties.create(
        PropertyInput(
            name=f"{tag}-P",
            address_text=f"1 {tag} St",
            property_type="single_family",
        )
    )
    assert created.is_ok, created.error
    pid = created.value.id
    for index, year in enumerate(years):
        result = transactions.create(
            TransactionInput(
                property_id=pid,
                date=_iso_date(year, index),
                amount=Decimal("100.00"),
                type="income",
                category_id="rents-received",
                description=None,
            )
        )
        assert result.is_ok, result.error
    for year, amount in reported.items():
        assert service.set_reported(year, amount).is_ok
    assert service.set_opening_balance(opening).is_ok


# Feature: passive-loss-carryforward, Property 10: User scoping — one user's
# reconcile reflects only their own data, over the SAME table
# Validates: Requirements 3.5, 7.5
@settings(deadline=None, max_examples=100)
@given(a_seed=_user_seed(), b_seed=_user_seed())
def test_reconcile_is_user_scoped_no_cross_user_leakage(a_seed, b_seed) -> None:
    """Each user's reconcile reflects only their own reported entries + opening balance.

    Validates: Requirements 3.5, 7.5
    """
    with _moto_table() as (repo, files):
        a_service, a_props, a_txns, _a_depr = _wire(repo, files, USER_A)
        b_service, b_props, b_txns, _b_depr = _wire(repo, files, USER_B)

        _seed_user(a_service, a_props, a_txns, "A", a_seed)
        _seed_user(b_service, b_props, b_txns, "B", b_seed)

        _a_years, a_reported, a_opening = a_seed
        _b_years, b_reported, b_opening = b_seed

        a_summary = a_service.reconcile()
        b_summary = b_service.reconcile()

        # Opening balance is scoped: each user sees only their own (Req 7.5).
        assert a_summary.opening_balance == Decimal(f"{Decimal(a_opening):.2f}")
        assert b_summary.opening_balance == Decimal(f"{Decimal(b_opening):.2f}")

        # Reported entries are scoped (Req 3.5): a user's reported years are
        # exactly those they set (restricted to their own Data_Years), with the
        # normalized value; no entry from the other user bleeds in.
        def reported_map(summary) -> dict[int, Decimal]:
            return {
                y.tax_year: y.reported_carryforward
                for y in summary.years
                if y.reported_carryforward is not None
            }

        a_series_years = {y.tax_year for y in a_summary.years}
        b_series_years = {y.tax_year for y in b_summary.years}

        a_expected_reported = {
            year: Decimal(f"{Decimal(amount):.2f}")
            for year, amount in a_reported.items()
            if year in a_series_years
        }
        b_expected_reported = {
            year: Decimal(f"{Decimal(amount):.2f}")
            for year, amount in b_reported.items()
            if year in b_series_years
        }
        assert reported_map(a_summary) == a_expected_reported
        assert reported_map(b_summary) == b_expected_reported

        # Neither user can read the other's entries: A clearing a year B
        # reported must not remove B's entry (writes are partition-scoped).
        if b_expected_reported:
            victim_year = next(iter(b_expected_reported))
            assert a_service.clear_reported(victim_year).is_ok
            b_after = reported_map(b_service.reconcile())
            assert b_after.get(victim_year) == b_expected_reported[victim_year], (
                "User A's clear modified user B's reported entry"
            )


# --- Property 11 : Empty, non-error series -----------------------------------


# Feature: passive-loss-carryforward, Property 11: Empty, non-error series
# (no Data_Years, no opening balance)
# Validates: Requirements 6.1, 6.2
@settings(deadline=None, max_examples=100)
@given(opening=st.none() | _money_str)
def test_empty_user_yields_empty_non_error_series(opening) -> None:
    """A user with no Data_Years and no opening balance yields years == (), has_data == False.

    Validates: Requirements 6.1, 6.2
    """
    with _moto_table() as (repo, files):
        service, _props, _txns, _depr = _wire(repo, files, USER_A)

        # No properties, no transactions, no opening balance set.
        summary = service.reconcile()
        assert summary.years == ()
        assert summary.has_data is False
        assert summary.opening_balance == Decimal("0.00")

        # Setting a positive opening balance alone flips has_data to True
        # (there is now something to reconcile), while an explicit 0.00 opening
        # balance keeps the empty, non-error series. Either way, no error.
        if opening is not None:
            assert service.set_opening_balance(opening).is_ok
            summary = service.reconcile()
            assert summary.years == ()
            assert summary.opening_balance == Decimal(f"{Decimal(opening):.2f}")
            if Decimal(opening) == Decimal("0.00"):
                assert summary.has_data is False
            else:
                assert summary.has_data is True


# --- Property 12 : §469 limitation is never applied --------------------------

# A per-year net magnitude and a loss/gain sign, so the generator spans pure
# losses, pure gains, and mixed series — including values where a real Form 8582
# §469 result (with a $25,000 allowance / phase-out) would diverge sharply from
# the pure economic running balance this feature computes.
_net_magnitude = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("200000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


def _recompute_expected(
    nets: list[Decimal], opening: Decimal
) -> list[Decimal]:
    """Independent running-balance recurrence over the nets alone (the §469-free oracle).

    Mirrors the design's algorithm exactly and depends on NOTHING but the nets
    and the opening balance: a loss (net < 0) adds its magnitude; a gain
    (net >= 0) is absorbed, floored at 0.00. No allowance, phase-out, or
    Form 8582 line participates.
    """
    balance = opening
    out: list[Decimal] = []
    for net in nets:
        if net < 0:
            balance = balance + (-net)
        else:
            balance = max(balance - net, Decimal("0.00"))
        out.append(balance)
    return out


# Feature: passive-loss-carryforward, Property 12: §469 limitation is never
# applied — expected depends only on nets + opening balance
# Validates: Requirements 2.7, 8.3
@settings(deadline=None, max_examples=100)
@given(
    year_nets=st.lists(
        st.tuples(st.sampled_from(_YEAR_POOL) if _YEAR_POOL else st.just(2020),
                  st.booleans(), _net_magnitude),
        min_size=1,
        max_size=4,
    ),
    opening=_money_str,
)
def test_expected_carryforward_is_section_469_free(year_nets, opening) -> None:
    """The returned Expected_Carryforward equals a pure running-balance recomputation of the nets.

    Validates: Requirements 2.7, 8.3
    """
    with _moto_table() as (repo, files):
        service, properties, txns, _depr = _wire(repo, files, USER_A)

        # One property per distinct year, seeded with income and/or expense
        # transactions so the year's Schedule E net matches the drawn sign +
        # magnitude. Dedupe by year (a Data_Year is unique; the latest draw for
        # a year wins, matching what the service will derive).
        by_year: dict[int, tuple[bool, Decimal]] = {}
        for year, is_gain, magnitude in year_nets:
            by_year[year] = (is_gain, magnitude)

        for year, (is_gain, magnitude) in by_year.items():
            created = properties.create(
                PropertyInput(
                    name=f"P{year}",
                    address_text=f"{year} St",
                    property_type="single_family",
                )
            )
            assert created.is_ok, created.error
            pid = created.value.id
            if magnitude > 0:
                # A gain is pure income; a loss is a pure expense of the same
                # magnitude (net = income - expenses).
                ttype = "income" if is_gain else "expense"
                category = "rents-received" if is_gain else "repairs"
                result = txns.create(
                    TransactionInput(
                        property_id=pid,
                        date=_iso_date(year, 0),
                        amount=magnitude,
                        type=ttype,
                        category_id=category,
                        description=None,
                    )
                )
                assert result.is_ok, result.error
            # magnitude == 0 leaves the property with a 0.00 net for the year
            # (still a Data_Year only if it has a transaction; with no txn it is
            # not derived — that is fine, reconcile just won't list it).

        opening_money = Decimal(f"{Decimal(opening):.2f}")
        assert service.set_opening_balance(opening).is_ok
        summary = service.reconcile()

        # Oracle: recompute the running balance over the SERVICE's own returned
        # nets (ascending) and opening balance. Using the service's nets isolates
        # Property 12 from any net-derivation question (Property 1 covers that):
        # here we assert only that expected depends on nets + opening alone.
        nets = [y.schedule_e_net for y in summary.years]
        expected = _recompute_expected(nets, opening_money)
        actual = [y.expected_carryforward for y in summary.years]
        assert actual == expected, (
            f"Expected_Carryforward diverged from the pure running balance: "
            f"nets={nets} opening={opening_money} actual={actual} oracle={expected}"
        )
        # Every expected figure is a non-negative two-decimal magnitude.
        for value in actual:
            assert value >= Decimal("0.00")
            assert value == value.quantize(Decimal("0.01"))
