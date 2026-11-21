"""Property-based test: no properties yields an empty trends series.

Feature: dashboard-year-over-year-trends, Property 10: No properties yields an
empty series.

Validates: Requirements 11.4

``DashboardService.trends_summary()`` (``services/dashboard.py``) lists the
authenticated user's properties once through the injected, user-scoped
``PropertyService`` and returns ``TrendsSummary(years=())`` immediately when the
user owns none. This property drives that universally: an "empty" user owns no
properties, while a *different* user in the same single-table DynamoDB owns
arbitrary generated Schedule E data (properties, transactions, and depreciable
assets across varied tax years). The empty user's series must be exactly the
empty tuple regardless of how much data the other user owns — the other user's
property-years must never leak into the empty user's series.

The oracle is trivial and exact: the only acceptable result is
``summary.years == ()``. The interesting work is in the generator, which builds
a non-trivial portfolio for the *other* user so that, were scoping broken, the
empty user's series would be non-empty.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring the fixture pattern in
``test_dashboard_net_property.py`` and the sibling trends property tests. Two
user-scoped ``PropertyService`` instances share the one repository/table so the
test exercises real cross-user isolation rather than a faked store.
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

# The user under test owns nothing; the "other" user owns the generated noise.
EMPTY_USER = "user-empty"
OTHER_USER = "user-other"


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the ``DashboardService`` scoped to the empty user plus the *other*
    user's ``PropertyService``/``TransactionService``/``DepreciationService``,
    all bound to the one shared repository/table. GSI1 is required by
    ``PropertyService.create`` (property-meta mirror); GSI2 is the tax-year
    partition that depreciation schedules read through. The empty user's
    ``DashboardService`` is wired with its own user-scoped ``PropertyService``
    so ``trends_summary()`` only ever sees the empty user's (zero) properties.
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

        # The user under test: owns no properties. Its DashboardService is
        # scoped to EMPTY_USER via its own PropertyService.
        empty_properties = PropertyService(repo, EMPTY_USER)
        transactions = TransactionService(repo, files)
        depreciation = DepreciationService(repo)
        empty_reports = ReportingService(transactions, depreciation, empty_properties)
        empty_dashboard = DashboardService(
            empty_properties, empty_reports, depreciation, transactions
        )

        # The other user: owns the generated noise in the same table.
        other_properties = PropertyService(repo, OTHER_USER)

        yield empty_dashboard, other_properties, transactions, depreciation


# --- Strategies --------------------------------------------------------------
#
# Arbitrary Schedule E data for the OTHER user: a handful of properties, each
# with transactions and depreciable assets across varied, non-contiguous tax
# years. Were scoping broken, any of this would surface in the empty user's
# series, so the generator aims to produce a non-trivial portfolio.

_YEAR_POOL = list(range(2016, 2031))

_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_SPECS = [
    ("income", "rents-received"),
    ("income", "royalties-received"),
    ("expense", "repairs"),
    ("expense", "utilities"),
]

_cost_basis = st.decimals(
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
        "cost_basis": _cost_basis,
        "placed_in_service_date": _placed_date,
        "recovery_period_years": _recovery,
    }
)


@st.composite
def _txn_spec(draw: st.DrawFn) -> tuple[int, str, str, Decimal]:
    """One (tax_year, type, category_id, amount) transaction spec."""
    year = draw(st.sampled_from(_YEAR_POOL))
    ttype, category = draw(st.sampled_from(_SPECS))
    amount = draw(_amounts)
    return year, ttype, category, amount


@st.composite
def _property_spec(draw: st.DrawFn):
    """One property's (transaction-specs, asset-specs) seed for the other user."""
    txns = draw(st.lists(_txn_spec(), min_size=0, max_size=6))
    assets = draw(st.lists(_asset_spec, min_size=0, max_size=3))
    return txns, assets


def _iso_date(year: int, index: int) -> str:
    """A deterministic in-year ISO date, cycling day/month to stay valid."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


# Feature: dashboard-year-over-year-trends, Property 10: No properties yields an
# empty series.
@settings(deadline=None, max_examples=100)
@given(other_properties_specs=st.lists(_property_spec(), min_size=0, max_size=3))
def test_no_properties_yields_empty_series(
    other_properties_specs: list[tuple[list[tuple[int, str, str, Decimal]], list[dict]]],
) -> None:
    """The empty user's trends series is ``()`` regardless of the other user's data.

    Validates: Requirements 11.4
    """
    with _moto_service() as (
        empty_dashboard,
        other_properties,
        transactions,
        depreciation,
    ):
        # Populate the OTHER user's portfolio with arbitrary Schedule E data.
        for p_index, (txns, asset_specs) in enumerate(other_properties_specs):
            created = other_properties.create(
                PropertyInput(
                    name=f"Other{p_index}",
                    address_text=f"{p_index} Other St",
                    property_type="single_family",
                )
            )
            assert created.is_ok, created.error
            pid = created.value.id

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

        # The empty user owns no properties, so its series must be exactly empty
        # — none of the other user's property-years may leak in (Req 11.4).
        summary = empty_dashboard.trends_summary()
        assert summary.years == (), (
            f"expected an empty series for a user owning no properties, got "
            f"{summary.years!r}"
        )
