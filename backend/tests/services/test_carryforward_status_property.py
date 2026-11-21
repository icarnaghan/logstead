"""Property-based test: carryforward status classification is total and correct.

Feature: passive-loss-carryforward, Property 7: Status classification is total
and correct.

Design Property 7 (Requirements 4.1, 4.2, 4.3, 4.4), re-pointed by the
carryforward-carry-in-semantics feature: the reported value is the Form 8582
"Prior years unallowed losses" figure, i.e. the balance carried INTO the year.
*For any* authenticated user with Schedule E data producing several Data_Years,
and *for any* subset of those years assigned a Reported_Carry_In (equal to that
year's Expected_Carry_In, or off by any non-zero amount), the
``Reconciliation_Status`` the ``CarryforwardService`` assigns every reconciled
year is exactly one of ``unreported`` / ``ok`` / ``carried`` / ``mismatch``:

* ``unreported`` iff no reported entry exists for the year (Req 4.1, 4.4);
* otherwise ``ok`` iff the reported value is within ``STATUS_TOLERANCE`` of the
  year's ``expected_carry_in`` (Req 4.2);
* otherwise ``carried`` iff the year is not the first, the previous year is
  reported, and the reported value is within ``STATUS_TOLERANCE`` of the
  PREVIOUS year's step (its
  Schedule E net, allowed loss and fully-allowed flag) applied to the previous
  year's reported value;
* otherwise ``mismatch`` (Req 4.3).

``drift`` is also checked: null iff unreported, else reported -
``expected_carry_in``.

Because a year's Expected_Carry_In is only known after the running balance is
rolled, the test first calls :meth:`CarryforwardService.reconcile` to read each
year's expected carry-in, then sets some reported entries equal to it (driving
``ok``) and some off by more than ``STATUS_TOLERANCE`` (tolerance plus one
dollar, driving ``mismatch``), leaving the remaining years unreported, then reconciles again and asserts the status of
every year.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring the fixture/service composition in
``test_trends_reconciliation_property.py``. Per-example provisioning is not
instantaneous, so the deadline is disabled; the example count is held at 100.
"""

from __future__ import annotations

import contextlib
from decimal import Decimal

import boto3
from hypothesis import example, given, settings
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
from logstead.util.money import money_to_str, to_money

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"

# A small spread of distinct, non-contiguous, completed tax years transactions
# may be dated within, so the generated series spans several Data_Years. All are
# safely below the latest-completed-tax-year cap (current calendar year minus
# one), so none are dropped by the Data_Year derivation.
_TAX_YEARS = [2018, 2019, 2020, 2022, 2023]

# A deliberate mismatch must differ from expected by MORE than the status
# tolerance: the tolerance plus one whole dollar.
_MISMATCH_OFFSET = STATUS_TOLERANCE + Decimal("1.00")


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed CarryforwardService plus the collaborators needed to
    seed data, bound to freshly created resources so each Hypothesis example
    runs against a clean store. The CarryforwardService is constructed WITH the
    transaction and depreciation services so its Data_Year derivation picks up
    transaction years.
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
# Each transaction is a (type, category, amount, description, year) tuple. A
# small spread of known, valid categories is used so the amount /
# missing-field / unknown-category paths never confound this property: income
# and expense lines, one expense being "Other" (Line 19, requires a non-blank
# description). Mixing income and expense across years produces a realistic mix
# of gain and loss years, so the rolled Expected_Carryforward takes a range of
# non-zero and zero values.
_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000.00"),
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


# A property is an arbitrary (non-empty) list of transactions so the series
# reliably has at least one Data_Year to classify.
_property_txns = st.lists(_txn(), min_size=1, max_size=10)


def _iso_date(year: int, index: int) -> str:
    """A deterministic in-year ISO date, cycling day/month to stay valid."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _seed(properties, transactions, properties_txns):
    """Create the generated properties and transactions through the services."""
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


def _assert_statuses_total_and_correct(service: CarryforwardService) -> None:
    """Reconcile and assert every year's status matches the tolerance rule.

    Compares each year's reported carry-in with its ``expected_carry_in``: no
    ``reported_carryforward`` is ``unreported``; within ``STATUS_TOLERANCE`` is
    ``ok``; within ``STATUS_TOLERANCE`` of the previous year's step on the
    previous reported value is ``carried``; anything else is ``mismatch``. The ``status`` field is a
    single Literal, so asserting the expected value proves totality and
    correctness together.
    """
    summary = service.reconcile()
    prior_reported: Decimal | None = None
    prior_year = None
    for index, year in enumerate(summary.years):
        reported = year.reported_carryforward
        # Chain value: the PREVIOUS year's step applied to the previous year's
        # REPORTED carry-in; only defined for a non-first year whose prior is
        # reported.
        chain: Decimal | None = None
        if index > 0 and prior_reported is not None:
            net = prior_year.schedule_e_net
            if net >= 0:
                effective = Decimal("0.00")
            elif prior_year.fully_allowed:
                effective = -net
            else:
                effective = prior_year.allowed_loss
            if net < 0:
                chain = to_money(
                    prior_reported + max(-net - effective, Decimal("0.00"))
                )
            else:
                chain = to_money(max(prior_reported - net, Decimal("0.00")))
        if reported is None:
            expected_status = "unreported"
        elif abs(reported - year.expected_carry_in) <= STATUS_TOLERANCE:
            expected_status = "ok"
        elif chain is not None and abs(reported - chain) <= STATUS_TOLERANCE:
            expected_status = "carried"
        else:
            expected_status = "mismatch"
        assert year.status == expected_status, (
            year.tax_year,
            money_to_str(year.expected_carry_in),
            None if reported is None else money_to_str(reported),
            year.status,
            expected_status,
        )
        # The status must be one of exactly the four known classifications.
        assert year.status in {"ok", "mismatch", "carried", "unreported"}
        # Drift is informational: null iff unreported, else
        # reported - expected carry-in.
        if reported is None:
            assert year.drift is None
        else:
            assert year.drift == to_money(reported - year.expected_carry_in)
        prior_reported = reported
        prior_year = year


# Feature: passive-loss-carryforward, Property 7: Status classification is total
# and correct
# Validates: Requirements 4.1, 4.2, 4.3, 4.4
@settings(deadline=None, max_examples=100)
@given(
    properties_txns=st.lists(_property_txns, min_size=1, max_size=3),
    # Per Data_Year, choose how to classify it: leave unreported, make it ok
    # (report == expected), or make it mismatch (report == expected +/- more
    # than the status tolerance).
    # Drawn as a long-enough list of choices zipped against the derived years.
    choices=st.lists(
        st.sampled_from(["unreported", "ok", "mismatch_up", "mismatch_down"]),
        min_size=0,
        max_size=40,
    ),
)
def test_status_classification_is_total_and_correct(
    properties_txns: list[list[tuple[str, str, Decimal, str | None, int]]],
    choices: list[str],
) -> None:
    """Every reconciled year gets exactly one, correct Reconciliation_Status.

    Validates: Requirements 4.1, 4.2, 4.3, 4.4
    """
    with _moto_service() as (service, properties, transactions):
        _seed(properties, transactions, properties_txns)

        # Read each year's Expected_Carryforward first — a reported value can
        # only be set equal to (ok) or off from (mismatch) a known expected.
        first = service.reconcile()

        for index, year in enumerate(first.years):
            # Cycle through the drawn choices so each year gets a classification
            # even when fewer choices than years were drawn.
            choice = choices[index % len(choices)] if choices else "unreported"
            # The reported value is the Form 8582 carry-in, so it is compared
            # with (and set relative to) the year's Expected_Carry_In.
            expected = year.expected_carry_in
            if choice == "ok":
                result = service.set_reported(
                    year.tax_year, money_to_str(expected)
                )
                assert result.is_ok, result.error
            elif choice == "mismatch_up":
                # Above expected by more than the tolerance — non-negative.
                result = service.set_reported(
                    year.tax_year,
                    money_to_str(to_money(expected + _MISMATCH_OFFSET)),
                )
                assert result.is_ok, result.error
            elif choice == "mismatch_down":
                # Below by more than the tolerance when that stays
                # non-negative; otherwise above (set_reported rejects
                # negatives).
                if expected >= _MISMATCH_OFFSET:
                    off = to_money(expected - _MISMATCH_OFFSET)
                else:
                    off = to_money(expected + _MISMATCH_OFFSET)
                result = service.set_reported(year.tax_year, money_to_str(off))
                assert result.is_ok, result.error
            # "unreported": set nothing for this year.

        _assert_statuses_total_and_correct(service)


# A deterministic example: a loss year immediately followed by a year whose
# Expected_Carryforward is non-zero, with that next year's Reported_Carryforward
# set to "0.00". The reported 0.00 differs from the carried-forward non-zero
# expected, so that year MUST classify as `mismatch` (the signature of a
# forgotten carryover). 2018 is a pure loss (expenses only) that drives the
# running balance up; 2019 carries that balance forward (its own net is zero, no
# transactions), so its Expected_Carryforward equals 2018's loss magnitude,
# which is non-zero.
# Feature: passive-loss-carryforward, Property 7: loss-year-then-next-year
# reported 0.00 yields mismatch
# Validates: Requirements 4.1, 4.2, 4.3, 4.4
@settings(deadline=None, max_examples=1)
@given(sentinel=st.just(None))
@example(sentinel=None)
def test_loss_year_then_next_year_reported_zero_is_mismatch(sentinel) -> None:
    """A carried-forward non-zero expected vs. a reported 0.00 is a mismatch.

    Validates: Requirements 4.1, 4.2, 4.3, 4.4
    """
    with _moto_service() as (service, properties, transactions):
        created = properties.create(
            PropertyInput(
                name="LossProp",
                address_text="1 Loss Ln",
                property_type="single_family",
            )
        )
        assert created.is_ok, created.error
        pid = created.value.id

        # 2018: a pure loss — a single expense, no income. This drives the
        # running Suspended_Loss_Balance up to the expense magnitude.
        loss = transactions.create(
            TransactionInput(
                property_id=pid,
                date="2018-03-15",
                amount=Decimal("5000.00"),
                type="expense",
                category_id="repairs",
            )
        )
        assert loss.is_ok, loss.error

        # 2019: give the year data (so it is a Data_Year) that nets to exactly
        # zero — one income and one equal expense — so no gain absorbs the prior
        # loss. The 2018 loss therefore carries forward unchanged, making 2019's
        # Expected_Carryforward non-zero (== 5000.00).
        inc = transactions.create(
            TransactionInput(
                property_id=pid,
                date="2019-04-10",
                amount=Decimal("1000.00"),
                type="income",
                category_id="rents-received",
            )
        )
        assert inc.is_ok, inc.error
        exp = transactions.create(
            TransactionInput(
                property_id=pid,
                date="2019-05-10",
                amount=Decimal("1000.00"),
                type="expense",
                category_id="utilities",
            )
        )
        assert exp.is_ok, exp.error

        first = service.reconcile()
        by_year = {y.tax_year: y for y in first.years}
        assert 2018 in by_year and 2019 in by_year, [
            y.tax_year for y in first.years
        ]

        # The 2019 Expected_Carryforward must be the carried-forward non-zero
        # loss magnitude, not zero.
        assert by_year[2019].expected_carry_in > Decimal("0.00"), (
            money_to_str(by_year[2019].expected_carry_in)
        )

        # Report 0.00 for 2019 — the "forgot to carry it forward" shape.
        result = service.set_reported(2019, "0.00")
        assert result.is_ok, result.error

        final = service.reconcile()
        final_by_year = {y.tax_year: y for y in final.years}
        assert final_by_year[2019].status == "mismatch", (
            money_to_str(final_by_year[2019].expected_carry_in),
            None
            if final_by_year[2019].reported_carryforward is None
            else money_to_str(final_by_year[2019].reported_carryforward),
            final_by_year[2019].status,
        )

        # And the full series still classifies totally and correctly.
        _assert_statuses_total_and_correct(service)
