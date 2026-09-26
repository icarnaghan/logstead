"""Property-based test: dashboard net equals the sum of per-property nets.

Design Property 26 (Requirements 11.1, 11.2): *for any* set of properties and
transactions for a tax year, the dashboard portfolio net income or loss equals
the sum of the per-property net income or loss values for that year.

``DashboardService.portfolio_summary(tax_year)`` (``services/dashboard.py``)
lists the user's properties and derives each property's income / expense / net
directly from that property's Schedule E report totals
(``ReportingService.report_for(pid, year).totals``), then rolls those up into a
portfolio :class:`DashboardSummary`. This property drives that aggregation
universally: it generates ``1..k`` properties, each with an arbitrary mix of
income and expense transactions dated within a single target tax year, persists
them through the real composed services, then asserts (exact ``Decimal``):

    (a) ``summary.net`` equals the sum of the per-property ``net`` values;
    (b) ``summary.total_income`` / ``summary.total_expenses`` equal the sums of
        the per-property income / expenses;
    (c) each per-property ``PropertySummary.net`` equals that property's
        Schedule E report net (the dashboard matches the report).

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring the fixture pattern in ``test_dashboard.py`` /
``test_report.py``. Per-example provisioning is not instantaneous, so the
deadline is disabled; the example count is held at 100 to keep the moto-backed
run reasonable.
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
TAX_YEAR = 2024


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed Dashboard, Reporting, Property, and Transaction services
    bound to freshly created resources so each Hypothesis example runs against a
    clean store with no aggregate faked.
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
        dashboard = DashboardService(properties, reports)
        yield dashboard, reports, properties, transactions


# --- Strategies ---------------------------------------------------------------
#
# Each transaction is an (type, category, amount) triple dated within the target
# tax year. A small spread of known, valid categories is used so the amount /
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
def _txn(draw: st.DrawFn) -> tuple[str, str, Decimal, str | None]:
    """One (type, category_id, amount, description) transaction spec.

    "Other" (Line 19) carries a required non-blank description; every other
    category leaves it unset.
    """
    ttype, category = draw(st.sampled_from(_INCOME_SPECS + _EXPENSE_SPECS))
    amount = draw(_amounts)
    description: str | None = None
    if category == "other":
        description = draw(
            st.text(min_size=1, max_size=20).filter(lambda s: s.strip())
        )
    return ttype, category, amount, description


# A property is an arbitrary (possibly empty) list of transactions.
_property_txns = st.lists(_txn(), min_size=0, max_size=10)


def _iso_date(index: int) -> str:
    """A deterministic in-year ISO date, cycling day/month to stay valid."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{TAX_YEAR:04d}-{month:02d}-{day:02d}"


# Feature: logstead, Property 26: Dashboard net equals the sum of per-property nets
@settings(deadline=None, max_examples=100)
@given(properties_txns=st.lists(_property_txns, min_size=1, max_size=4))
def test_dashboard_net_equals_sum_of_per_property_nets(
    properties_txns: list[list[tuple[str, str, Decimal, str | None]]],
) -> None:
    """Portfolio net == sum of per-property nets, matching each report net.

    Validates: Requirements 11.1, 11.2
    """
    with _moto_service() as (dashboard, reports, properties, transactions):
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

            for t_index, (ttype, category, amount, description) in enumerate(txns):
                result = transactions.create(
                    TransactionInput(
                        property_id=pid,
                        date=_iso_date(t_index),
                        amount=amount,
                        type=ttype,
                        category_id=category,
                        description=description,
                    )
                )
                assert result.is_ok, result.error

        summary = dashboard.portfolio_summary(TAX_YEAR)

        assert summary.tax_year == TAX_YEAR
        assert summary.has_properties is True
        # One per-property summary per property.
        assert {p.property_id for p in summary.properties} == set(property_ids)

        # (a) Portfolio net equals the exact-Decimal sum of the per-property nets.
        assert summary.net == sum(
            (p.net for p in summary.properties), Decimal("0.00")
        )

        # (b) Portfolio income / expenses equal the sums of the per-property
        # income / expenses.
        assert summary.total_income == sum(
            (p.total_income for p in summary.properties), Decimal("0.00")
        )
        assert summary.total_expenses == sum(
            (p.total_expenses for p in summary.properties), Decimal("0.00")
        )

        # (c) Each per-property figure matches that property's Schedule E report
        # totals, so the dashboard is consistent with the report.
        for ps in summary.properties:
            report = reports.report_for(ps.property_id, TAX_YEAR)
            assert report.is_ok, report.error
            totals = report.value.totals
            assert ps.total_income == totals.total_income
            assert ps.total_expenses == totals.total_expenses
            assert ps.net == totals.net

        # And the portfolio net also equals the sum of the per-property report
        # nets directly.
        report_net_sum = sum(
            (
                reports.report_for(pid, TAX_YEAR).value.totals.net
                for pid in property_ids
            ),
            Decimal("0.00"),
        )
        assert summary.net == report_net_sum
