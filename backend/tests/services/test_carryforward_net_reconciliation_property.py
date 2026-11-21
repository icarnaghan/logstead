"""Property-based test: each reconciled year's Schedule E net reconciles.

Feature: passive-loss-carryforward, Property 1: Schedule E net reconciles with
the reports.

Design Property 1 (Requirements 1.1, 1.2): *for any* authenticated user with
properties and income/expense transactions dated across varied, non-contiguous
tax years, every reconciled year's ``schedule_e_net`` returned by
``CarryforwardService.reconcile()`` equals, to the exact cent (zero ``Decimal``
difference), the portfolio sum across that user's properties of
``ReportingService.report_for(property_id, year).value.totals.net`` for the same
Tax_Year.

``CarryforwardService.reconcile()`` (``services/carryforward.py``) derives the
Schedule_E_Net for each Data_Year as the exact-cent sum, across the user's
properties, of each property's net straight from that property's Schedule E
report totals (``ReportingService.report_for(pid, year).value.totals.net``) —
the same report path the dashboard trends use. This property asserts that
derivation reconciles with the reports: it generates ``1..k`` properties, each
with an arbitrary mix of income and expense transactions dated across several
distinct tax years, persists them through the real composed services, then
asserts (exact ``Decimal``) that every reconciled year's ``schedule_e_net``
matches the independently recomputed portfolio report sum for that year.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring the fixture pattern in
``test_trends_reconciliation_property.py``. The ``CarryforwardService`` is
composed with the real PropertyService / TransactionService / DepreciationService
/ ReportingService so Data_Year derivation works end to end. Per-example
provisioning is not instantaneous, so the deadline is disabled; the example
count is held at 100 to keep the moto-backed run reasonable.
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

# A small spread of distinct tax years transactions may be dated within, so the
# reconciliation spans several Data_Years. The years are deliberately
# non-contiguous to exercise the real (gap-preserving) Data_Year derivation.
_TAX_YEARS = [2020, 2022, 2023, 2025]


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed CarryforwardService, ReportingService, PropertyService,
    and TransactionService bound to freshly created resources so each Hypothesis
    example runs against a clean store with nothing faked. The
    CarryforwardService is constructed WITH the transaction and depreciation
    services so ``_derive_data_years`` picks up transaction years.
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
        yield carryforward, reports, properties, transactions


# --- Strategies ---------------------------------------------------------------
#
# Each transaction is a (type, category, amount, description, year) tuple. A
# small spread of known, valid categories is used so the amount /
# missing-field / unknown-category paths never confound this property: two
# income lines and three expense lines, one of which is "Other" (Line 19). The
# "Other" category requires a non-blank description, which the generator always
# supplies for that category, so every transaction creates successfully.
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


@st.composite
def _txn(draw: st.DrawFn) -> tuple[str, str, Decimal, str | None, int]:
    """One (type, category_id, amount, description, tax_year) transaction spec.

    "Other" (Line 19) carries a required non-blank description; every other
    category leaves it unset. The tax year is drawn from a small spread of
    distinct, non-contiguous years so the reconciliation spans several
    Data_Years.
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


# Feature: passive-loss-carryforward, Property 1: Schedule E net reconciles with
# the reports, to the cent
@settings(deadline=None, max_examples=100)
@given(properties_txns=st.lists(_property_txns, min_size=1, max_size=4))
def test_carryforward_schedule_e_net_reconciles_with_report(
    properties_txns: list[list[tuple[str, str, Decimal, str | None, int]]],
) -> None:
    """Every reconciled year's schedule_e_net == portfolio report-net sum.

    Validates: Requirements 1.1, 1.2
    """
    with _moto_service() as (carryforward, reports, properties, transactions):
        property_ids: list[str] = []
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
            property_ids.append(pid)

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

        summary = carryforward.reconcile()

        # For every reconciled year, the derived Schedule_E_Net equals the
        # independently recomputed portfolio sum, across the user's properties,
        # of that property's Schedule E report net for the same year, to the
        # exact cent (zero Decimal difference).
        for reconciled in summary.years:
            expected_net = Decimal("0.00")
            for pid in property_ids:
                report = reports.report_for(pid, reconciled.tax_year)
                assert report.is_ok, report.error
                expected_net += report.value.totals.net
            assert reconciled.schedule_e_net == expected_net, (
                reconciled.tax_year,
                reconciled.schedule_e_net,
                expected_net,
            )
