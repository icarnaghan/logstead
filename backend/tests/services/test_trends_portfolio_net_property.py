"""Property-based test: trends portfolio net is the exact-cent sum of per-property nets.

Feature: dashboard-year-over-year-trends, Property 2: Portfolio net is the
exact-cent sum of per-property nets.

Design Property 2 (Requirements 6.5, 7.5): *for any* Data_Year, the Trends_Series
entry's portfolio ``net`` equals the exact-cent sum of that year's per-property
nets, with zero rounding difference across all properties. The same exactness
holds for the portfolio ``total_income`` / ``total_expenses`` against the
per-property income / expense figures.

``DashboardService.trends_summary()`` (``services/dashboard.py``) derives the
ascending set of Data_Years and, for each year, loops the user's properties,
taking each :class:`PropertyYearPoint`'s income / expense / net straight from
that property's Schedule E report totals and accumulating the portfolio totals
as exact-cent ``Decimal`` sums. This property drives that aggregation
universally: it generates ``1..k`` properties, each with an arbitrary mix of
income and expense transactions dated across several tax years, persists them
through the real composed services, then asserts for **every** ``TrendYear``:

    (a) ``year.net`` equals the exact-``Decimal`` sum of that year's
        per-property ``net`` values;
    (b) ``year.total_income`` / ``year.total_expenses`` equal the exact-``Decimal``
        sums of that year's per-property income / expenses.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring ``test_dashboard_net_property.py``. The
``TransactionService`` is injected into the ``DashboardService`` because the
trends path derives Data_Years from the properties' transaction years.
Per-example provisioning is not instantaneous, so the deadline is disabled; the
example count is held at 100 to keep the moto-backed run reasonable.
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
from logstead.services.dashboard import DashboardService
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"

# The spread of tax years transactions may be dated in; trends must produce one
# TrendYear per year that actually has data, so using several years exercises
# the per-year portfolio summation that this property is about.
_TAX_YEARS = [2021, 2022, 2023, 2024]


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed Dashboard, Reporting, Property, and Transaction services
    bound to freshly created resources so each Hypothesis example runs against a
    clean store with no aggregate faked. The Transaction service is injected
    into the Dashboard service so the trends path can derive Data_Years from the
    properties' transaction years.
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
        dashboard = DashboardService(properties, reports, depreciation, transactions)
        yield dashboard, reports, properties, transactions


# --- Strategies ---------------------------------------------------------------
#
# Each transaction is a (type, category, amount, year, description) spec. A
# small spread of known, valid categories is used so the amount /
# missing-field / unknown-category paths never confound this property: two
# income lines and three expense lines, one of which is "Other" (Line 19). The
# "Other" category requires a non-blank description, which the generator always
# supplies for that category, so every transaction creates successfully. The
# tax year is drawn from a fixed spread so a property's data spans several years.
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
def _txn(draw: st.DrawFn) -> tuple[str, str, Decimal, int, str | None]:
    """One (type, category_id, amount, tax_year, description) transaction spec.

    "Other" (Line 19) carries a required non-blank description; every other
    category leaves it unset.
    """
    ttype, category = draw(st.sampled_from(_INCOME_SPECS + _EXPENSE_SPECS))
    amount = draw(_amounts)
    year = draw(st.sampled_from(_TAX_YEARS))
    description: str | None = None
    if category == "other":
        description = draw(
            st.text(min_size=1, max_size=20).filter(lambda s: s.strip())
        )
    return ttype, category, amount, year, description


# A property is an arbitrary (possibly empty) list of transactions.
_property_txns = st.lists(_txn(), min_size=0, max_size=10)


def _iso_date(year: int, index: int) -> str:
    """A deterministic in-year ISO date, cycling day/month to stay valid."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


# Feature: dashboard-year-over-year-trends, Property 2: Portfolio net is the exact-cent sum of per-property nets
@settings(deadline=None, max_examples=100)
@given(properties_txns=st.lists(_property_txns, min_size=1, max_size=4))
def test_portfolio_net_is_exact_cent_sum_of_per_property_nets(
    properties_txns: list[list[tuple[str, str, Decimal, int, str | None]]],
) -> None:
    """For every TrendYear, portfolio net/income/expenses == exact-cent sums.

    Validates: Requirements 6.5, 7.5
    """
    with _moto_service() as (dashboard, _reports, properties, transactions):
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

            for t_index, (ttype, category, amount, year, description) in enumerate(
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

        trends = dashboard.trends_summary()

        # Every property owned by the user appears in every TrendYear's points.
        for trend_year in trends.years:
            assert {p.property_id for p in trend_year.properties} == set(
                property_ids
            )

            # (a) Portfolio net equals the exact-Decimal sum of the year's
            # per-property nets, with zero rounding difference.
            expected_net = sum(
                (p.net for p in trend_year.properties), Decimal("0.00")
            )
            assert trend_year.net == expected_net, (
                f"year {trend_year.tax_year}: portfolio net {trend_year.net} != "
                f"sum of per-property nets {expected_net}"
            )

            # (b) Portfolio income / expenses equal the exact-Decimal sums of the
            # year's per-property income / expenses.
            expected_income = sum(
                (p.total_income for p in trend_year.properties), Decimal("0.00")
            )
            expected_expenses = sum(
                (p.total_expenses for p in trend_year.properties), Decimal("0.00")
            )
            assert trend_year.total_income == expected_income, (
                f"year {trend_year.tax_year}: portfolio income "
                f"{trend_year.total_income} != sum {expected_income}"
            )
            assert trend_year.total_expenses == expected_expenses, (
                f"year {trend_year.tax_year}: portfolio expenses "
                f"{trend_year.total_expenses} != sum {expected_expenses}"
            )
