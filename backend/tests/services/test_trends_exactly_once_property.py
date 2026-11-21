"""Property test — each per-(property, year) derivation runs exactly once.

Feature: dashboard-year-over-year-trends, Property 9: Each per-(property, year)
derivation runs exactly once per pair.

Validates: Requirements 11.1

``DashboardService.trends_summary()`` (``services/dashboard.py``) derives the
ascending Data_Years for the user once and, for each Data_Year, loops the
user's properties making exactly one
``ReportingService.report_for(property_id, year)`` call and exactly one
``DepreciationService.property_depreciation_for_year(property_id, year)`` call
per (property, Data_Year) pair — the N-properties x M-years loop of design
Requirement 11.1. This property drives that loop universally and asserts, via
counting spies, that neither derivation is ever skipped nor repeated for any
(pid, year) pair.

Strategy
--------
Each example provisions ``1..k`` properties, each seeded with an arbitrary mix
of income/expense transactions and depreciable assets placed across a small
spread of non-contiguous tax years, so the derived Data_Year set is non-trivial
and varies per example. The two per-(property, year) derivations
(``report_for`` and ``property_depreciation_for_year``) are wrapped with spies
that record every ``(property_id, year)`` argument pair while delegating to the
real service methods, so the produced series stays correct. After calling
``trends_summary()`` the test asserts that:

    * every (pid, year) pair where ``pid`` is an owned property and ``year`` is
      a derived Data_Year was invoked exactly once on BOTH spies (no missing,
      no duplicate call), and
    * no spy was invoked for any pair outside the owned-property x Data_Year
      grid.

The expected Data_Year set is read back from the service's own
``_derive_data_years`` over the listed properties (the same derivation the
method uses), keeping the oracle exact without duplicating the union maths.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring the sibling trends property tests. Per-example
provisioning is not instantaneous, so the deadline is disabled and the example
count is held at 100.
"""

from __future__ import annotations

import contextlib
from collections import Counter
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.depreciation import AssetInput
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


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed ``(DashboardService, PropertyService,
    TransactionService, DepreciationService, ReportingService)`` bound to
    freshly created resources so each Hypothesis example runs against a clean
    store. GSI1 is required by ``PropertyService.create``; GSI2 is the tax-year
    partition depreciation schedules read through. The ``DashboardService`` is
    wired WITH the transaction service so ``_derive_data_years`` picks up
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
        files = S3FileAdapter(s3, BUCKET)
        properties = PropertyService(repo, USER)
        transactions = TransactionService(repo, files)
        depreciation = DepreciationService(repo)
        reports = ReportingService(transactions, depreciation, properties)
        dashboard = DashboardService(properties, reports, depreciation, transactions)
        yield dashboard, properties, transactions, depreciation, reports


class _CountingReports:
    """Spy wrapping the real ``ReportingService``, counting ``report_for``.

    Records every ``(property_id, year)`` pair passed to ``report_for`` while
    delegating to the real implementation, so the resulting series is still
    computed exactly as it would be without the spy.
    """

    def __init__(self, inner: ReportingService) -> None:
        self._inner = inner
        self.calls: Counter[tuple[str, int]] = Counter()

    def report_for(self, property_id: str, year: int):
        self.calls[(property_id, year)] += 1
        return self._inner.report_for(property_id, year)

    def __getattr__(self, name):
        # Delegate anything else (none is needed here) to the real service.
        return getattr(self._inner, name)


class _CountingDepreciation:
    """Spy wrapping the real ``DepreciationService``.

    Counts every ``(property_id, year)`` pair passed to
    ``property_depreciation_for_year`` while delegating to the real service.
    ``_derive_data_years`` also calls ``list_assets`` / ``schedule_for`` through
    this object, so those are passed through transparently (and not counted).
    """

    def __init__(self, inner: DepreciationService) -> None:
        self._inner = inner
        self.calls: Counter[tuple[str, int]] = Counter()

    def property_depreciation_for_year(self, property_id: str, year: int):
        self.calls[(property_id, year)] += 1
        return self._inner.property_depreciation_for_year(property_id, year)

    def __getattr__(self, name):
        return getattr(self._inner, name)


# --- Strategies --------------------------------------------------------------
#
# A small spread of non-contiguous tax years so the derived Data_Year grid is
# non-trivial and varies per example. Transactions anchor the income/expense
# half of a Data_Year; assets anchor the depreciation half.

_YEAR_POOL = [2019, 2021, 2022, 2024, 2026]

_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_INCOME_SPECS = [("income", "rents-received"), ("income", "royalties-received")]
_EXPENSE_SPECS = [("expense", "repairs"), ("expense", "utilities")]


@st.composite
def _txn(draw: st.DrawFn) -> tuple[str, str, Decimal, int]:
    """One (type, category_id, amount, tax_year) transaction spec."""
    ttype, category = draw(st.sampled_from(_INCOME_SPECS + _EXPENSE_SPECS))
    amount = draw(_amounts)
    year = draw(st.sampled_from(_YEAR_POOL))
    return ttype, category, amount, year


_asset_cost_basis = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("500000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_recovery = st.sampled_from(
    [Decimal("5"), Decimal("7"), Decimal("15"), Decimal("27.5"), Decimal("39")]
)

_placed_date = st.builds(
    lambda y, m, d: f"{y:04d}-{m:02d}-{d:02d}",
    st.sampled_from(_YEAR_POOL),
    st.integers(min_value=1, max_value=12),
    st.integers(min_value=1, max_value=28),
)

_asset_spec = st.fixed_dictionaries(
    {
        "cost_basis": _asset_cost_basis,
        "placed_in_service_date": _placed_date,
        "recovery_period_years": _recovery,
    }
)


@st.composite
def _property_spec(draw: st.DrawFn):
    """One property's (transaction-specs, asset-specs) seed."""
    txns = draw(st.lists(_txn(), min_size=0, max_size=5))
    assets = draw(st.lists(_asset_spec, min_size=0, max_size=2))
    return txns, assets


def _iso_date(year: int, index: int) -> str:
    """A deterministic in-year ISO date; year is what the Data_Year keys on."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


# Feature: dashboard-year-over-year-trends, Property 9: Each per-(property, year)
# derivation runs exactly once per pair
@settings(deadline=None, max_examples=100)
@given(property_specs=st.lists(_property_spec(), min_size=1, max_size=3))
def test_each_derivation_runs_exactly_once_per_property_year_pair(
    property_specs: list[tuple[list[tuple[str, str, Decimal, int]], list[dict]]],
) -> None:
    """report_for and property_depreciation_for_year: exactly once per (pid, year).

    Validates: Requirements 11.1
    """
    with _moto_service() as (
        dashboard,
        properties,
        transactions,
        depreciation,
        reports,
    ):
        property_ids: list[str] = []
        for p_index, (txns, asset_specs) in enumerate(property_specs):
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

            for t_index, (ttype, category, amount, year) in enumerate(txns):
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

            for spec in asset_specs:
                asset_result = depreciation.create_asset(
                    AssetInput(
                        property_id=pid,
                        description="Asset",
                        cost_basis=spec["cost_basis"],
                        placed_in_service_date=spec["placed_in_service_date"],
                        recovery_period_years=spec["recovery_period_years"],
                    )
                )
                assert asset_result.is_ok, asset_result.error

        # The expected (pid, year) grid: every owned property x every derived
        # Data_Year. Read the Data_Years back from the service's own derivation
        # so the oracle matches the method exactly without re-deriving the union.
        listed = properties.list()
        expected_years = dashboard._derive_data_years(listed)
        expected_pairs = {
            (prop.id, year) for prop in listed for year in expected_years
        }

        # Wrap the two per-(property, year) derivations with counting spies that
        # delegate to the real services, then drive the full trends path.
        report_spy = _CountingReports(reports)
        depreciation_spy = _CountingDepreciation(depreciation)
        spied_dashboard = DashboardService(
            properties, report_spy, depreciation_spy, transactions
        )

        spied_dashboard.trends_summary()

        # Exactly once per (pid, year) pair on BOTH derivations: no missing
        # call (every expected pair present with count 1) and no duplicate or
        # stray call (no pair recorded more than once, none outside the grid).
        assert set(report_spy.calls) == expected_pairs, (
            f"report_for pairs {set(report_spy.calls)} != expected "
            f"{expected_pairs}"
        )
        assert all(count == 1 for count in report_spy.calls.values()), (
            f"report_for invoked more than once for some pair: "
            f"{ {k: v for k, v in report_spy.calls.items() if v != 1} }"
        )

        assert set(depreciation_spy.calls) == expected_pairs, (
            f"property_depreciation_for_year pairs "
            f"{set(depreciation_spy.calls)} != expected {expected_pairs}"
        )
        assert all(count == 1 for count in depreciation_spy.calls.values()), (
            f"property_depreciation_for_year invoked more than once for some "
            f"pair: { {k: v for k, v in depreciation_spy.calls.items() if v != 1} }"
        )
