"""Property-based test: the Expected_Carryforward is a correct, non-negative
running balance.

Design Property 2 — *Expected is a correct running balance* (Requirements 2.1,
2.2, 2.3, 2.4, 2.5): for any sequence of per-year Schedule_E_Nets and any
Opening_Balance, processing the Data_Years ascending yields, for each year,
``expected == max(prior_balance - net, 0)`` when ``net >= 0`` and
``expected == prior_balance + (-net)`` when ``net < 0``; and each year's
``expected`` is the balance carried into the next reconciled year, with the
first year's prior balance being the Opening_Balance.

Design Property 3 — *Expected is never negative* (Requirements 2.4, 2.6): for
any inputs, every Expected_Carryforward is ``>= 0.00`` and is a two-decimal
``Decimal`` (exponent ``-2``).

``CarryforwardService.reconcile()`` (``services/carryforward.py``) lists the
user's properties, derives the ascending Data_Years via the shared dashboard
helper, sums each property's ``report_for(pid, year).value.totals.net`` to get
the year's Schedule_E_Net, and rolls a non-negative suspended-loss balance
forward from the Opening_Balance (a loss adds its magnitude, a gain is absorbed
and floored at ``0.00``). This test provisions real properties + transactions
producing varied per-year nets — a deliberate mix of loss and gain years across
non-contiguous tax years — plus an Opening_Balance set via
``service.set_opening_balance(...)``, then walks the returned ``years``
ascending and re-derives the expected balance independently from each year's
returned ``schedule_e_net`` (the oracle is the running-balance recurrence over
the returned nets starting from the Opening_Balance).

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

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"

# A small spread of distinct, deliberately non-contiguous tax years the
# generated transactions are dated within, so the reconciled series spans
# several Data_Years with gaps (exercising the real gap-preserving derivation).
_TAX_YEARS = [2020, 2022, 2023, 2025]


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed CarryforwardService bound to freshly created resources
    so each Hypothesis example runs against a clean store. The service is
    constructed exactly as the carryforward route composes it:
    ``CarryforwardService(repo, USER, reports, properties, transactions,
    depreciation)`` — the transaction + depreciation collaborators let the
    shared ``derive_data_years`` helper pick up the transaction years.
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
# per-year nets (some loss years, some gain years), which is exactly what
# exercises both arms of the running-balance recurrence.
_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# (type, category_id) pairs across a spread of Schedule E lines.
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


@st.composite
def _txn(draw: st.DrawFn) -> tuple[str, str, Decimal, str | None, int]:
    """One (type, category_id, amount, description, tax_year) transaction spec.

    "Other" (Line 19) carries a required non-blank description; every other
    category leaves it unset. The tax year is drawn from the small spread of
    distinct, non-contiguous years so the series spans several Data_Years.
    """
    ttype, category = draw(st.sampled_from(_INCOME_SPECS + _EXPENSE_SPECS))
    amount = draw(_amounts)
    year = draw(st.sampled_from(_TAX_YEARS))
    description: str | None = None
    if category == "other":
        description = draw(
            st.text(min_size=1, max_size=20).filter(lambda s: s.strip())
        )
    return ttype, category, amount, description, year


# A property is an arbitrary (possibly empty) list of transactions.
_property_txns = st.lists(_txn(), min_size=0, max_size=10)


def _iso_date(year: int, index: int) -> str:
    """A deterministic in-year ISO date, cycling day/month to stay valid."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


# Feature: passive-loss-carryforward, Property 2+3: the Expected_Carryforward
# is a correct, non-negative two-decimal running balance over the returned nets
# plus the opening balance.
@settings(deadline=None, max_examples=100)
@given(
    properties_txns=st.lists(_property_txns, min_size=1, max_size=4),
    opening=_opening_amounts,
)
def test_carryforward_expected_is_a_correct_non_negative_running_balance(
    properties_txns: list[list[tuple[str, str, Decimal, str | None, int]]],
    opening: Decimal,
) -> None:
    """Expected == running balance over the returned nets + opening; never < 0.

    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
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

        summary = service.reconcile()

        # The opening balance round-trips as the balance carried into the
        # earliest reconciled year (Req 2.2).
        assert summary.opening_balance == opening

        # Walk the returned years ascending, re-deriving the expected balance
        # independently from each year's returned schedule_e_net. The oracle is
        # the running-balance recurrence over the returned nets starting from
        # the Opening_Balance.
        prior_balance = summary.opening_balance
        prev_year: int | None = None
        for reconciled in summary.years:
            # Years are processed ascending (Req 2.1).
            if prev_year is not None:
                assert reconciled.tax_year > prev_year, (
                    prev_year,
                    reconciled.tax_year,
                )
            prev_year = reconciled.tax_year

            net = reconciled.schedule_e_net
            if net < 0:
                # A loss increases the balance by its magnitude (Req 2.3).
                oracle = prior_balance + (-net)
            else:
                # A gain is absorbed, floored at zero (Req 2.4).
                oracle = max(prior_balance - net, Decimal("0.00"))

            # The step relation holds exactly to the cent (Req 2.3, 2.4, 2.5).
            assert reconciled.expected_carryforward == oracle, (
                reconciled.tax_year,
                prior_balance,
                net,
                reconciled.expected_carryforward,
                oracle,
            )

            # Expected is never negative and is a two-decimal Decimal
            # (exponent -2) (Req 2.4, 2.6).
            assert reconciled.expected_carryforward >= Decimal("0.00"), (
                reconciled.tax_year,
                reconciled.expected_carryforward,
            )
            assert isinstance(reconciled.expected_carryforward, Decimal)
            assert reconciled.expected_carryforward.as_tuple().exponent == -2, (
                reconciled.tax_year,
                reconciled.expected_carryforward,
            )

            # Each year's expected is the balance carried into the next year
            # (Req 2.5).
            prior_balance = reconciled.expected_carryforward
