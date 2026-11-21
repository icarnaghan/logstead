"""Property-based test: every series year is total (all figures present).

Feature: dashboard-year-over-year-trends, Property 7: Every series year is
total — all figures present, non-null, two-decimal.

Design Property 7 (Requirements 11.2): *for any* authenticated user, set of
properties, transactions, and depreciable assets, every money figure returned
by :meth:`DashboardService.trends_summary` is present, non-null, and a
two-decimal ``Decimal`` (quantized to exponent ``-2``). Concretely, for every
:class:`TrendYear` in the series:

    (a) the portfolio ``total_income`` / ``total_expenses`` / ``net`` /
        ``depreciation_total`` are each a non-null ``Decimal`` with exponent
        ``-2``; and
    (b) every :class:`PropertyYearPoint` in that year carries a non-null
        ``total_income`` / ``total_expenses`` / ``net``, each a ``Decimal`` with
        exponent ``-2``.

No figure is missing (every field is populated) and no figure is ``None``.

``DashboardService.trends_summary()`` (``services/dashboard.py``) carries every
money figure through :func:`to_money`, which quantizes to two decimal places, so
a well-formed series never surfaces a ``None`` or a non-two-decimal amount — even
for properties or years with no data (which contribute ``0.00``). This property
drives that totality universally: each example generates ``1..k`` properties,
each with an arbitrary mix of income / expense transactions dated across a
spread of non-contiguous tax years and an arbitrary set of depreciable assets
placed in service across several years, persists them through the real composed
services, then asserts the completeness / non-null / two-decimal invariants over
every figure in the whole series.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring the fixture pattern in
``test_trends_reconciliation_property.py`` / ``test_dashboard_net_property.py``.
Per-example provisioning is not instantaneous, so the deadline is disabled; the
example count is held at 100 to keep the moto-backed run reasonable.

Validates: Requirements 11.2
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
USER = "user-abc"

# A property's money figures must be two-decimal Decimals: exponent exactly -2.
TWO_PLACES_EXPONENT = -2

# A small spread of distinct, non-contiguous tax years so the generated series
# spans several Data_Years with gaps.
_TAX_YEARS = [2020, 2022, 2023, 2025]


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed Dashboard, Property, Transaction, and Depreciation
    services bound to freshly created resources so each Hypothesis example runs
    against a clean store with no aggregate faked. The ``DashboardService`` is
    constructed WITH the transaction service so ``_derive_data_years`` picks up
    transaction years, matching the router's ``_dashboard_service_or_503``
    composition.
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
        yield dashboard, properties, transactions, depreciation


# --- Strategies ---------------------------------------------------------------
#
# Each property carries an arbitrary (possibly empty) mix of income / expense
# transactions and an arbitrary (possibly empty) set of depreciable assets. The
# "Other" (Line 19) expense category requires a non-blank description, which the
# generator always supplies for that category, so every transaction creates
# successfully. Years are drawn from a small non-contiguous spread so the series
# spans several Data_Years with gaps; properties and years with no data must
# still surface a complete two-decimal 0.00 figure.

_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1000000.00"),
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


_cost_basis = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("5000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_placed_date = st.builds(
    lambda y, m, d: f"{y:04d}-{m:02d}-{d:02d}",
    st.integers(min_value=2018, max_value=2024),
    st.integers(min_value=1, max_value=12),
    st.integers(min_value=1, max_value=28),
)

_recovery = st.sampled_from(
    [Decimal("27.5"), Decimal("5"), Decimal("7"), Decimal("15"), Decimal("39")]
)

_asset_spec = st.fixed_dictionaries(
    {
        "cost_basis": _cost_basis,
        "placed_in_service_date": _placed_date,
        "recovery_period_years": _recovery,
    }
)

# A property is an arbitrary (possibly empty) list of transactions plus an
# arbitrary (possibly empty) list of depreciable assets.
_property_spec = st.fixed_dictionaries(
    {
        "txns": st.lists(_txn(), min_size=0, max_size=8),
        "assets": st.lists(_asset_spec, min_size=0, max_size=3),
    }
)


def _iso_date(year: int, index: int) -> str:
    """A deterministic in-year ISO date, cycling day/month to stay valid."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _assert_two_decimal(value: Decimal, context: object) -> None:
    """Assert ``value`` is a non-null two-decimal ``Decimal`` (exponent -2)."""
    assert value is not None, context
    assert isinstance(value, Decimal), (type(value), context)
    assert value.as_tuple().exponent == TWO_PLACES_EXPONENT, (value, context)


# Feature: dashboard-year-over-year-trends, Property 7: Every series year is
# total — all figures present, non-null, two-decimal.
@settings(deadline=None, max_examples=100)
@given(properties_specs=st.lists(_property_spec, min_size=1, max_size=4))
def test_every_series_figure_is_present_nonnull_two_decimal(
    properties_specs: list[dict],
) -> None:
    """Every money figure in the series is non-null and quantized to -2.

    Validates: Requirements 11.2
    """
    with _moto_service() as (dashboard, properties, transactions, depreciation):
        for p_index, spec in enumerate(properties_specs):
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
                spec["txns"]
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

            for asset_spec in spec["assets"]:
                result = depreciation.create_asset(
                    AssetInput(
                        property_id=pid,
                        description="Asset",
                        cost_basis=asset_spec["cost_basis"],
                        placed_in_service_date=asset_spec["placed_in_service_date"],
                        recovery_period_years=asset_spec["recovery_period_years"],
                    )
                )
                assert result.is_ok, result.error

        summary = dashboard.trends_summary()

        for trend_year in summary.years:
            where = ("portfolio", trend_year.tax_year)
            # (a) Portfolio figures: present, non-null, two-decimal.
            _assert_two_decimal(trend_year.total_income, where)
            _assert_two_decimal(trend_year.total_expenses, where)
            _assert_two_decimal(trend_year.net, where)
            _assert_two_decimal(trend_year.depreciation_total, where)

            # (b) Every per-property point's three figures: present, non-null,
            # two-decimal — no figure missing or None.
            for point in trend_year.properties:
                point_where = (point.property_id, trend_year.tax_year)
                _assert_two_decimal(point.total_income, point_where)
                _assert_two_decimal(point.total_expenses, point_where)
                _assert_two_decimal(point.net, point_where)
