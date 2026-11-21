"""Property test — trends are scoped to the authenticated user, no leakage.

Feature: dashboard-year-over-year-trends, Property 8: User scoping — no
cross-user leakage.

Validates: Requirements 6.6

``DashboardService.trends_summary()`` (``services/dashboard.py``) lists the
user's properties once through the injected, user-scoped
:class:`PropertyService` and derives every figure — the Data_Years, the
per-property points, and the portfolio totals — only from those properties.
This property drives two distinct users A and B over the *same* moto-backed
single table (each with its own ``PropertyService``, ``ReportingService``,
``DepreciationService``, ``TransactionService``, and ``DashboardService`` bound
to its own user id) and asserts the isolation is total in both directions:

* Every property id that appears anywhere in A's series (in any ``TrendYear``'s
  ``properties`` points) is one of A's own property ids and never one of B's —
  and symmetrically for B (Req 6.6).
* A's Data_Years (the ``tax_year`` of each ``TrendYear``) are exactly the union
  of years derived from A's own transactions and depreciation; none of B's
  B-only years leak in — and symmetrically for B. "B-only years" are years B
  has data in but A does not, which is the observable signature of a
  cross-user Data_Year leak.

Each user's data spans several deliberately non-contiguous years with its own
properties, transactions, and depreciation assets, so the derivation is
exercised across varied, overlapping and non-overlapping year sets. Overlapping
years (a year both users have data in) are allowed and must NOT be treated as a
leak — a shared year legitimately appears in both series — so the leak oracle
is specifically each user's *own* data-derived year set and *own* property-id
set, computed independently per user.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring ``test_trends_data_years_property.py`` and
``test_trends_reconciliation_property.py``. Per-example provisioning is not
instantaneous, so the deadline is disabled and the example count is held at 100.
"""

from __future__ import annotations

import contextlib
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
from logstead.services.dashboard import DashboardService, _latest_tax_year
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
    DashboardService, PropertyService, TransactionService, DepreciationService
]:
    """Compose a full, user-scoped service stack for one user over the shared store.

    The ``DashboardService`` is built WITH the transaction service so
    ``_derive_data_years`` picks up that user's transaction years.
    """
    properties = PropertyService(repo, user_id)
    transactions = TransactionService(repo, files)
    depreciation = DepreciationService(repo)
    reports = ReportingService(transactions, depreciation, properties)
    dashboard = DashboardService(properties, reports, depreciation, transactions)
    return dashboard, properties, transactions, depreciation


# --- Strategies --------------------------------------------------------------
#
# Each user's years are drawn from a deliberately sparse pool so year sets are
# non-contiguous and the two users overlap on some years and diverge on others.

_YEAR_POOL = list(range(2016, 2031))

_txn_years = st.lists(st.sampled_from(_YEAR_POOL), min_size=0, max_size=5)

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
    """One property's (transaction-years, asset-specs) seed."""
    years = draw(_txn_years)
    assets = draw(st.lists(_asset_spec, min_size=0, max_size=3))
    return years, assets


# A user owns at least one property so its series is non-empty often enough to
# make the leakage assertions meaningful in both directions.
_user_spec = st.lists(_property_spec(), min_size=1, max_size=3)


def _iso_date(year: int, index: int) -> str:
    """A deterministic in-year ISO date; year is what the Data_Year keys on."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _seed_user(
    properties: PropertyService,
    transactions: TransactionService,
    depreciation: DepreciationService,
    user_tag: str,
    specs: list[tuple[list[int], list[dict]]],
) -> tuple[set[str], set[int]]:
    """Create a user's properties, transactions, and depreciation assets.

    Returns ``(own_property_ids, own_data_years)``: the set of this user's
    property ids and the set of Data_Years derived from *this user's own*
    transactions and materialized depreciation schedules — the independent
    oracle the leakage assertions compare against.
    """
    own_ids: set[str] = set()
    own_years: set[int] = set()

    for p_index, (txn_years, asset_specs) in enumerate(specs):
        created = properties.create(
            PropertyInput(
                name=f"{user_tag}-Prop{p_index}",
                address_text=f"{p_index} {user_tag} St",
                property_type="single_family",
            )
        )
        assert created.is_ok, created.error
        pid = created.value.id
        own_ids.add(pid)

        for t_index, year in enumerate(txn_years):
            result = transactions.create(
                TransactionInput(
                    property_id=pid,
                    date=_iso_date(year, t_index),
                    amount=Decimal("100.00"),
                    type="income",
                    category_id="rents-received",
                    description=None,
                )
            )
            assert result.is_ok, result.error
            own_years.add(year)

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

        for asset in depreciation.list_assets(pid):
            for row in depreciation.schedule_for(pid, asset.id):
                own_years.add(row.tax_year)

    return own_ids, own_years


def _series_property_ids(summary) -> set[str]:
    """Every property id appearing anywhere in a trends summary's points."""
    ids: set[str] = set()
    for trend_year in summary.years:
        for point in trend_year.properties:
            ids.add(point.property_id)
    return ids


def _series_years(summary) -> set[int]:
    """Every Data_Year (``tax_year``) present in a trends summary."""
    return {trend_year.tax_year for trend_year in summary.years}


# Feature: dashboard-year-over-year-trends, Property 8: User scoping — no
# cross-user leakage
@settings(deadline=None, max_examples=100)
@given(a_specs=_user_spec, b_specs=_user_spec)
def test_trends_summary_is_user_scoped_no_cross_user_leakage(
    a_specs: list[tuple[list[int], list[dict]]],
    b_specs: list[tuple[list[int], list[dict]]],
) -> None:
    """A's series reflects only A's property-ids/years, and B's only B's.

    Validates: Requirements 6.6
    """
    with _moto_table() as (repo, files):
        a_dash, a_props, a_txns, a_depr = _wire(repo, files, USER_A)
        b_dash, b_props, b_txns, b_depr = _wire(repo, files, USER_B)

        a_ids, a_years_raw = _seed_user(a_props, a_txns, a_depr, "A", a_specs)
        b_ids, b_years_raw = _seed_user(b_props, b_txns, b_depr, "B", b_specs)

        # trends_summary() caps Data_Years at the latest completed tax year
        # (the current year can't be filed yet and depreciation schedules run
        # decades out), so the per-user oracles are capped the same way.
        latest = _latest_tax_year()
        a_years = {year for year in a_years_raw if year <= latest}
        b_years = {year for year in b_years_raw if year <= latest}

        a_summary = a_dash.trends_summary()
        b_summary = b_dash.trends_summary()

        a_series_ids = _series_property_ids(a_summary)
        b_series_ids = _series_property_ids(b_summary)
        a_series_years = _series_years(a_summary)
        b_series_years = _series_years(b_summary)

        # --- Property-id scoping: A's series mentions only A's ids ------------
        assert a_series_ids <= a_ids, (
            f"A's trends contain property ids outside A's own set: "
            f"{a_series_ids - a_ids}"
        )
        assert not (a_series_ids & b_ids), (
            f"B's property ids leaked into A's trends: {a_series_ids & b_ids}"
        )
        # Symmetric: B's series mentions only B's ids.
        assert b_series_ids <= b_ids, (
            f"B's trends contain property ids outside B's own set: "
            f"{b_series_ids - b_ids}"
        )
        assert not (b_series_ids & a_ids), (
            f"A's property ids leaked into B's trends: {b_series_ids & a_ids}"
        )

        # --- Data_Year scoping: each user's years derive only from own data ---
        # A's series years are exactly A's own data-derived years; no B-only
        # year (a year B has but A does not) may appear, and vice-versa.
        assert a_series_years == a_years, (
            f"A's Data_Years {sorted(a_series_years)} != A's own data years "
            f"{sorted(a_years)}"
        )
        b_only_years = b_years - a_years
        assert not (a_series_years & b_only_years), (
            f"B-only Data_Years leaked into A's trends: "
            f"{sorted(a_series_years & b_only_years)}"
        )

        assert b_series_years == b_years, (
            f"B's Data_Years {sorted(b_series_years)} != B's own data years "
            f"{sorted(b_years)}"
        )
        a_only_years = a_years - b_years
        assert not (b_series_years & a_only_years), (
            f"A-only Data_Years leaked into B's trends: "
            f"{sorted(b_series_years & a_only_years)}"
        )
