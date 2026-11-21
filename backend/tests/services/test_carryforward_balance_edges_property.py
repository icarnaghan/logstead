"""Property-based tests: carryforward running-balance edge behaviours.

These exercise the two extreme shapes of the Expected_Carryforward running
balance through the real, moto-composed ``CarryforwardService.reconcile()``:

**Property 4 — A profitable run drives the balance to zero and holds.** Given a
positive Opening_Balance followed by gain-only years whose cumulative gain meets
or exceeds the opening balance, the Expected_Carryforward reaches ``0.00`` and
holds at ``0.00`` for every subsequent year, no matter how large the later gains
grow (a gain is absorbed and floored at zero, never driving the balance
negative).

**Property 5 — Pure-loss accumulation.** Given only loss years (and an
Opening_Balance), each year's Expected_Carryforward equals the Opening_Balance
plus the cumulative magnitude of the losses through that year.

To control whether a Data_Year is a gain or a loss without re-deriving any math
here, each year is seeded with real transactions through the composed services:
an income-only year has a positive Schedule_E_Net (a gain), and an expense-only
year has a negative Schedule_E_Net (a loss). The service derives the net from
those transactions via ``ReportingService.report_for`` exactly as production
does, so these tests assert the running-balance behaviour end to end rather than
against a re-implemented formula.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring the fixture pattern in
``test_trends_reconciliation_property.py``. Per-example provisioning is not
instantaneous, so the deadline is disabled; the example count is held at 100.
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
from logstead.util.money import to_money

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"

# A contiguous ascending span of distinct tax years the generated per-year
# amounts are placed into, so each seeded year becomes its own Data_Year and the
# running balance is exercised across several ascending steps.
_BASE_YEAR = 2018

# Valid Schedule E lines used to make a year unambiguously a gain or a loss: an
# income-only year nets positive, an expense-only year nets negative.
_INCOME_CATEGORY = "rents-received"
_EXPENSE_CATEGORY = "repairs"


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed Carryforward, Reporting, Property, and Transaction
    services bound to freshly created resources so each Hypothesis example runs
    against a clean store. ``CarryforwardService`` is constructed WITH the
    transaction and depreciation services so its Data_Year derivation picks up
    the seeded transaction years.
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
        carryforward = CarryforwardService(
            repo, USER, reports, properties, transactions, depreciation
        )
        yield carryforward, properties, transactions


def _create_property(properties: PropertyService) -> str:
    """Create one property for the user and return its id."""
    created = properties.create(
        PropertyInput(
            name="Prop",
            address_text="1 Main St",
            property_type="single_family",
        )
    )
    assert created.is_ok, created.error
    return created.value.id


def _seed_year(
    transactions: TransactionService,
    property_id: str,
    year: int,
    ttype: str,
    category: str,
    amount: Decimal,
) -> None:
    """Seed a single income- or expense-only transaction into ``year``.

    An income-only year nets positive (a gain); an expense-only year nets
    negative (a loss). The net magnitude equals ``amount``.
    """
    result = transactions.create(
        TransactionInput(
            property_id=property_id,
            date=f"{year:04d}-06-15",
            amount=amount,
            type=ttype,
            category_id=category,
        )
    )
    assert result.is_ok, result.error


# Per-year magnitudes. Kept well inside two-decimal range so cumulative sums
# over several years never lose precision and gains can meet/exceed the opening.
_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


# Feature: passive-loss-carryforward, Property 4: A profitable run drives the
# balance to zero and holds.
@settings(deadline=None, max_examples=100)
@given(
    opening=_amounts,
    gains=st.lists(_amounts, min_size=1, max_size=6),
    extra_gain=_amounts,
)
def test_profitable_run_floors_at_zero_and_holds(
    opening: Decimal,
    gains: list[Decimal],
    extra_gain: Decimal,
) -> None:
    """A positive opening + sufficient gains reaches 0.00 and stays 0.00.

    A first gain year is made large enough to meet or exceed the opening
    balance, so the Expected_Carryforward hits ``0.00`` that year; every
    subsequent gain year (however large) holds it at ``0.00`` and never drives
    it negative.

    Validates: Requirements 2.3, 2.4
    """
    opening = to_money(opening)
    with _moto_service() as (carryforward, properties, transactions):
        pid = _create_property(properties)

        # Opening balance (positive).
        set_opening = carryforward.set_opening_balance(f"{opening:.2f}")
        assert set_opening.is_ok, set_opening.error

        # First gain year: large enough that cumulative gain >= opening, so the
        # balance is driven to 0.00 this year.
        first_gain = to_money(opening + to_money(gains[0]))
        _seed_year(
            transactions, pid, _BASE_YEAR, "income", _INCOME_CATEGORY, first_gain
        )
        # Subsequent gain years, each an arbitrary positive net.
        later = [to_money(g) for g in gains[1:]] + [to_money(extra_gain)]
        for offset, gain in enumerate(later, start=1):
            _seed_year(
                transactions,
                pid,
                _BASE_YEAR + offset,
                "income",
                _INCOME_CATEGORY,
                gain,
            )

        summary = carryforward.reconcile()

        # The reconciled years are exactly the seeded gain years, ascending.
        assert len(summary.years) == 1 + len(later)
        zero = to_money("0.00")
        for reconciled in summary.years:
            # Every year is a gain (net >= 0).
            assert reconciled.schedule_e_net >= zero, reconciled
            # Once a profitable run meets the opening, every year's expected is
            # floored at 0.00 and never negative. The first year already clears
            # the opening (first_gain >= opening), so all years are 0.00.
            assert reconciled.expected_carryforward == zero, reconciled
            assert reconciled.expected_carryforward >= zero, reconciled


# Feature: passive-loss-carryforward, Property 5: Pure-loss accumulation.
@settings(deadline=None, max_examples=100)
@given(
    opening=st.decimals(
        min_value=Decimal("0.00"),
        max_value=Decimal("100000.00"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    losses=st.lists(_amounts, min_size=1, max_size=6),
)
def test_pure_loss_accumulation(
    opening: Decimal,
    losses: list[Decimal],
) -> None:
    """Loss-only years accumulate to opening + cumulative loss magnitude.

    Each year's Expected_Carryforward equals the Opening_Balance plus the sum of
    the magnitudes of every loss through that year, with no absorption (there
    are no gain years to reduce the balance).

    Validates: Requirements 2.3, 2.4
    """
    opening = to_money(opening)
    losses = [to_money(loss) for loss in losses]
    with _moto_service() as (carryforward, properties, transactions):
        pid = _create_property(properties)

        set_opening = carryforward.set_opening_balance(f"{opening:.2f}")
        assert set_opening.is_ok, set_opening.error

        for offset, loss in enumerate(losses):
            _seed_year(
                transactions,
                pid,
                _BASE_YEAR + offset,
                "expense",
                _EXPENSE_CATEGORY,
                loss,
            )

        summary = carryforward.reconcile()

        assert len(summary.years) == len(losses)
        # Walk the reconciled years ascending, accumulating the expected balance
        # independently and asserting the service matches to the cent.
        running = opening
        for reconciled, loss in zip(summary.years, losses):
            # Each seeded year is a pure loss (net < 0, magnitude == loss).
            assert reconciled.schedule_e_net == to_money(-loss), reconciled
            running = to_money(running + loss)
            assert reconciled.expected_carryforward == running, (
                reconciled,
                running,
            )
