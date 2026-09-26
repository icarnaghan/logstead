"""Property-based test: reports are reproducible from persisted data alone.

Design Property 27 (Requirement 12.5): *for any* persisted data set, computing a
Schedule E report twice from stored data (with no cached aggregates) yields
identical line totals, depreciation, and net results.

``ReportingService.report_for(property_id, tax_year)`` and
``combined_report(...)`` derive every figure from persisted records —
transactions, materialized depreciation schedules, and stored usage days — with
no cached aggregate anywhere. This property drives that guarantee universally:
it generates a property with an arbitrary mix of income / expense transactions
(varied categories, including itemized "Other"), ``0..k`` depreciable assets,
and stored usage days, persists them, then computes the report twice and asserts
structural equality of the frozen :class:`ScheduleEReport` (header, lines,
other_items, totals).

To prove the report is derived from *persisted* data and not from any in-memory
state carried between calls, the second computation runs against a **fresh** set
of services (property / transaction / depreciation / reporting) constructed over
the *same* moto-backed table and bucket. If the report leaned on any cached
aggregate held by the first service instance, the fresh instance — which has
seen none of the writes in memory — would diverge. The same fresh-instance check
is applied to ``combined_report``.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket (needed to construct the
``S3FileAdapter``), mirroring the fixture pattern in ``test_report.py``.
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
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"
TAX_YEAR = 2024


def _create_table(ddb) -> None:
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


def _build_services(ddb, s3):
    """Compose Property / Transaction / Depreciation / Reporting services.

    A fresh call builds brand-new service objects (and a fresh repository /
    file adapter) bound to the given — already provisioned — moto clients, so a
    second computation shares no in-memory state with the first.
    """
    repo = DynamoRepository(ddb, TABLE_NAME)
    properties = PropertyService(repo, USER)
    transactions = TransactionService(repo, S3FileAdapter(s3, BUCKET))
    depreciation = DepreciationService(repo)
    service = ReportingService(transactions, depreciation, properties)
    return service, properties, transactions, depreciation


@contextlib.contextmanager
def _moto_clients():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the raw ``(ddb, s3)`` clients so a test can build one set of services
    to seed and compute, then build a *fresh* set over the same resources.
    """
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        yield ddb, s3


# --- Strategies ---------------------------------------------------------------
#
# A transaction is an (type, category, amount) triple dated within the target
# tax year. Categories are drawn from a varied set of real catalog lines,
# including "Other" (Line 19) which is itemized and requires a description — so
# reproducibility of the itemization is exercised too. Income transactions land
# on income lines; expense transactions on expense lines.
_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# (type, category_id) pairs across a spread of Schedule E lines.
_INCOME_CATEGORIES = ["rents-received", "royalties-received"]
_EXPENSE_CATEGORIES = ["repairs", "utilities", "insurance", "taxes", "advertising"]

_txn = st.one_of(
    st.tuples(
        st.tuples(st.just("income"), st.sampled_from(_INCOME_CATEGORIES)),
        _amounts,
        st.none(),
    ),
    st.tuples(
        st.tuples(st.just("expense"), st.sampled_from(_EXPENSE_CATEGORIES)),
        _amounts,
        st.none(),
    ),
    # "Other" expense (Line 19) carries a required free-text description that
    # feeds the itemization, so generate one.
    st.tuples(
        st.tuples(st.just("expense"), st.just("other")),
        _amounts,
        # The Other category (Line 19) requires a NON-BLANK description; filter
        # out whitespace-only strings the service would (correctly) reject.
        st.text(min_size=1, max_size=20).filter(lambda s: s.strip() != ""),
    ),
)

_txns = st.lists(_txn, min_size=0, max_size=12)

# An asset is a (cost_basis, placed-in-service day-of-year offset) pair. Cost
# basis is bounded so the 27.5-year straight-line schedule stays sane.
_asset = st.tuples(
    st.decimals(
        min_value=Decimal("100.00"),
        max_value=Decimal("500000.00"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    st.integers(min_value=0, max_value=330),
)
_assets = st.lists(_asset, min_size=0, max_size=3)

# Usage days for the year (feed the header).
_usage = st.tuples(
    st.integers(min_value=0, max_value=365),
    st.integers(min_value=0, max_value=365),
)


def _iso_date(index: int) -> str:
    """A deterministic in-year ISO date, cycling day/month to stay valid."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{TAX_YEAR:04d}-{month:02d}-{day:02d}"


def _iso_date_from_offset(offset: int) -> str:
    """An in-year ISO date from a 0..330 day-of-year-ish offset."""
    month = (offset // 28) % 12 + 1
    day = (offset % 28) + 1
    return f"{TAX_YEAR:04d}-{month:02d}-{day:02d}"


def _seed(properties, transactions, depreciation, txns, assets, usage):
    """Persist a property with the generated transactions, assets, and usage."""
    created = properties.create(
        PropertyInput(
            name="Repro",
            address_text="1 Repro St",
            property_type="single_family",
        )
    )
    assert created.is_ok, created.error
    pid = created.value.id

    fair_rental_days, personal_use_days = usage
    usage_result = properties.set_usage_days(
        pid, TAX_YEAR, fair_rental_days, personal_use_days
    )
    assert usage_result.is_ok, usage_result.error

    for t_index, ((ttype, category), amount, description) in enumerate(txns):
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

    for a_index, (cost_basis, offset) in enumerate(assets):
        asset = depreciation.create_asset(
            AssetInput(
                property_id=pid,
                description=f"Asset {a_index}",
                cost_basis=cost_basis,
                placed_in_service_date=_iso_date_from_offset(offset),
                recovery_period_years=Decimal("27.5"),
            )
        )
        assert asset.is_ok, asset.error

    return pid


# Feature: logstead, Property 27: Reports are reproducible from persisted data alone
@settings(deadline=None, max_examples=100)
@given(txns=_txns, assets=_assets, usage=_usage)
def test_reports_are_reproducible_from_persisted_data_alone(
    txns: list[tuple[tuple[str, str], Decimal, str | None]],
    assets: list[tuple[Decimal, int]],
    usage: tuple[int, int],
) -> None:
    """Computing a report twice from stored data yields identical results.

    The second computation runs against a *fresh* set of services over the same
    moto-backed table, proving the report derives from persisted records and not
    from any cached aggregate held by the first service instance.

    Validates: Requirement 12.5
    """
    with _moto_clients() as (ddb, s3):
        # First set of services seeds the data and computes the report.
        service_a, properties_a, transactions_a, depreciation_a = _build_services(
            ddb, s3
        )
        pid = _seed(properties_a, transactions_a, depreciation_a, txns, assets, usage)

        first = service_a.report_for(pid, TAX_YEAR)
        assert first.is_ok, first.error

        # Recompute with the same instance: no drift.
        again = service_a.report_for(pid, TAX_YEAR)
        assert again.is_ok, again.error
        assert first.value == again.value

        # Recompute with a FRESH set of services over the SAME table/bucket. If
        # any figure came from an in-memory cache rather than persisted data,
        # this fresh instance would diverge.
        service_b, _, _, _ = _build_services(ddb, s3)
        fresh = service_b.report_for(pid, TAX_YEAR)
        assert fresh.is_ok, fresh.error

        # Structural equality of the frozen dataclass covers header, lines,
        # other_items, and totals.
        assert fresh.value == first.value
        assert fresh.value.header == first.value.header
        assert fresh.value.lines == first.value.lines
        assert fresh.value.other_items == first.value.other_items
        assert fresh.value.totals == first.value.totals

        # combined_report is reproducible under a fresh instance too.
        combined_first = service_a.combined_report([pid], TAX_YEAR)
        assert combined_first.is_ok, combined_first.error
        combined_fresh = service_b.combined_report([pid], TAX_YEAR)
        assert combined_fresh.is_ok, combined_fresh.error
        assert combined_fresh.value == combined_first.value
