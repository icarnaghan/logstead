"""Property-based test: a property with no data in a Data_Year contributes 0.00.

Feature: dashboard-year-over-year-trends, Property 5: A property with no data in
a Data_Year contributes 0.00 and still appears.

Design Property 5 (Requirements 4.2, 11.3, 6.7): *for any* Data_Year in which a
given property has no Schedule E data (no transactions and no depreciation),
that property still appears as a :class:`PropertyYearPoint` in that year with
``total_income == total_expenses == net == "0.00"`` (two-decimal), and every
owned property appears in every :class:`TrendYear`.

``DashboardService.trends_summary()`` (``services/dashboard.py``) derives the
ascending Data_Years across the user's portfolio, then for each year loops the
properties — reusing ``ReportingService.report_for`` and
``DepreciationService.property_depreciation_for_year`` once per
(property, Data_Year) pair — appending a point for *every* property regardless
of whether it has data that year. A property with no data in a year yields a
zero report (or a non-ok report), both of which contribute ``0.00`` and still
append a point with ``net == 0.00``.

This property drives that universally: each example provisions a mix of
"active" properties (each carrying transactions in one or more generated tax
years, which define the Data_Years) and one or more "empty" properties that
carry no transactions and no depreciation at all. It then asserts, for every
year in the resulting series:

    (a) every owned property appears exactly once as a point (every property
        appears in every TrendYear);
    (b) each empty property's point has
        ``total_income == total_expenses == net == Decimal("0.00")`` and each
        figure is a two-decimal value;
    (c) the portfolio totals equal the exact-Decimal sum over the points, so
        the empty properties contribute nothing;
    (d) the year's ``depreciation_total`` is unaffected by the empty properties
        (they contribute ``0.00`` depreciation).

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring the fixture pattern in ``test_dashboard_net_property.py``.
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

ZERO = Decimal("0.00")


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed Dashboard, Property, and Transaction services bound to
    freshly created resources so each Hypothesis example runs against a clean
    store with no aggregate faked. The ``DashboardService`` is constructed with
    the ``TransactionService`` so the year-over-year trends path can derive the
    Data_Years.
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
        yield dashboard, properties, transactions


# --- Strategies ---------------------------------------------------------------
#
# An active property carries one or more transactions dated within one or more
# generated tax years; those years define the Data_Years. An empty property
# carries no transactions and no depreciation at all, so it must contribute
# 0.00 in every Data_Year while still appearing as a point.

_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# (type, category_id) pairs across a spread of Schedule E lines (no "Other", so
# no required-description path to satisfy here).
_SPECS = [
    ("income", "rents-received"),
    ("income", "royalties-received"),
    ("expense", "repairs"),
    ("expense", "utilities"),
]

# Distinct tax years the active properties may use; non-contiguous on purpose.
_years = st.sampled_from([2019, 2021, 2022, 2024])


@st.composite
def _active_txn(draw: st.DrawFn) -> tuple[int, str, str, Decimal]:
    """One (tax_year, type, category_id, amount) transaction spec."""
    year = draw(_years)
    ttype, category = draw(st.sampled_from(_SPECS))
    amount = draw(_amounts)
    return year, ttype, category, amount


# An active property: 1..6 transactions (so it always establishes >=1 Data_Year).
_active_property = st.lists(_active_txn(), min_size=1, max_size=6)


def _iso_date(year: int, index: int) -> str:
    """A deterministic in-year ISO date, cycling day/month to stay valid."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _make_property(properties: PropertyService, name: str) -> str:
    result = properties.create(
        PropertyInput(
            name=name,
            address_text=f"{name} St",
            property_type="single_family",
        )
    )
    assert result.is_ok, result.error
    return result.value.id


# Feature: dashboard-year-over-year-trends, Property 5: a property with no data
# in a Data_Year contributes 0.00 and still appears.
@settings(deadline=None, max_examples=100)
@given(
    active_properties=st.lists(_active_property, min_size=1, max_size=3),
    empty_count=st.integers(min_value=1, max_value=3),
)
def test_empty_property_contributes_zero_but_still_appears(
    active_properties: list[list[tuple[int, str, str, Decimal]]],
    empty_count: int,
) -> None:
    """An empty property is 0.00 in every year and still appears as a point.

    Validates: Requirements 4.2, 11.3, 6.7
    """
    with _moto_service() as (dashboard, properties, transactions):
        all_ids: list[str] = []
        empty_ids: set[str] = set()

        # Active properties carry transactions that define the Data_Years.
        for p_index, txns in enumerate(active_properties):
            pid = _make_property(properties, f"Active{p_index}")
            all_ids.append(pid)
            for t_index, (year, ttype, category, amount) in enumerate(txns):
                result = transactions.create(
                    TransactionInput(
                        property_id=pid,
                        date=_iso_date(year, t_index),
                        amount=amount,
                        type=ttype,
                        category_id=category,
                        description=None,
                    )
                )
                assert result.is_ok, result.error

        # Empty properties carry no transactions and no depreciation at all.
        for e_index in range(empty_count):
            pid = _make_property(properties, f"Empty{e_index}")
            all_ids.append(pid)
            empty_ids.add(pid)

        summary = dashboard.trends_summary()

        # The active properties established at least one Data_Year.
        assert summary.years, "expected at least one Data_Year from active data"

        owned = set(all_ids)
        for trend_year in summary.years:
            points = trend_year.properties
            point_ids = [p.property_id for p in points]

            # (a) Every owned property appears exactly once in every TrendYear.
            assert len(point_ids) == len(owned)
            assert set(point_ids) == owned

            by_id = {p.property_id: p for p in points}

            # (b) Each empty property's point is 0.00 across all three figures,
            # each a two-decimal value.
            for pid in empty_ids:
                point = by_id[pid]
                assert point.total_income == ZERO
                assert point.total_expenses == ZERO
                assert point.net == ZERO
                assert point.total_income.as_tuple().exponent == -2
                assert point.total_expenses.as_tuple().exponent == -2
                assert point.net.as_tuple().exponent == -2

            # (c) Portfolio totals equal the exact-Decimal sum over all points,
            # so the empty properties contribute nothing to income/expenses/net.
            assert trend_year.total_income == sum(
                (p.total_income for p in points), ZERO
            )
            assert trend_year.total_expenses == sum(
                (p.total_expenses for p in points), ZERO
            )
            assert trend_year.net == sum((p.net for p in points), ZERO)

            # (d) The empty properties contribute 0.00 depreciation, so dropping
            # them from the net-income sum leaves the portfolio net unchanged.
            active_net_sum = sum(
                (p.net for p in points if p.property_id not in empty_ids),
                ZERO,
            )
            assert trend_year.net == active_net_sum
