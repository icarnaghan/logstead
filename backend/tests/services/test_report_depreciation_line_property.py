"""Property-based test: the report's depreciation line equals computed depreciation.

Design Property 22 (Requirements 10.3, 7.5): *for any* property and tax year, the
report's Line 18 value equals the total property depreciation for that year
computed from the depreciation schedules.

``ReportingService.report_for`` (``services/report.py``) fills Line 18
(``DEPRECIATION_LINE == 18``) from
``DepreciationService.property_depreciation_for_year(property_id, tax_year)``,
which sums the materialized schedule rows for that (property, year). Line 18 is
**never** fed by a transaction: it is not an assignable Schedule E category
(Requirement 7.5 -- Line 18 is intentionally absent from the seeded catalog),
and ``_build_report`` explicitly guards against any transaction whose recorded
line is 18. So Line 18 depends **only** on the depreciation schedules, and is
invariant to the user's income/expense transactions.

This test drives that universally. For each example it provisions a fresh
property and:

* creates ``0..k`` depreciable assets with random cost basis, placed-in-service
  date (spanning all twelve months, some in earlier years so their schedule
  reaches into the target year), and recovery period (including the 27.5-year
  default); each ``create_asset`` materializes the asset's schedule;
* creates a random set of user transactions across **assignable** income and
  expense categories (none of which can be Line 18, since 18 is not assignable),
  including several Other/Line 19 expenses (which require a description).

It then computes the expected Line 18 total **independently in the test** as the
sum, over every created asset, of that asset's ``schedule_for`` row ``amount``
for the target tax year, and asserts:

* (a) ``report.line(18).total`` equals
  ``depreciation.property_depreciation_for_year(pid, year)`` equals the summed
  per-asset schedule amounts for that year (Requirement 10.3);
* (b) Line 18's kind is ``expense`` and it is included in ``total_expenses``;
* (c) Line 18 is invariant to the transactions -- rerunning the report after
  adding the transactions leaves Line 18 unchanged, i.e. no user transaction
  contributes to Line 18 (Requirements 10.3, 7.5).

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 for the property meta mirror + GSI2 for the tax-year partition the
report and ``property_depreciation_for_year`` read through) plus an S3 bucket
needed to construct the ``S3FileAdapter``, mirroring ``test_report.py``.
Per-example provisioning is not instantaneous, so the deadline is disabled; the
example count is held at 100.
"""

from __future__ import annotations

import contextlib
import datetime as dt
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
from logstead.services.category import CATEGORY_CATALOG
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import DEPRECIATION_LINE, ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"
TAX_YEAR = 2024

# The assignable catalog indexed by id, plus the income/expense id pools the
# transaction generator draws from. Line 18 is intentionally absent from this
# catalog (Requirement 7.5), so no drawn transaction can ever carry line 18.
_CATEGORY_BY_ID = {c.id: c for c in CATEGORY_CATALOG}
_INCOME_CATEGORY_IDS = tuple(c.id for c in CATEGORY_CATALOG if c.kind == "income")
_EXPENSE_CATEGORY_IDS = tuple(c.id for c in CATEGORY_CATALOG if c.kind == "expense")


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed ``(ReportingService, PropertyService, TransactionService,
    DepreciationService)`` bound to freshly created resources so each Hypothesis
    example runs against a clean store. GSI1 is required by
    ``PropertyService.create`` (property meta mirror); GSI2 is the tax-year
    partition both the report and ``property_depreciation_for_year`` read
    through.
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
        report = ReportingService(transactions, depreciation, properties)
        yield report, properties, transactions, depreciation


# --- Strategies --------------------------------------------------------------
#
# Assets are placed in service in the target year or up to a few years before it
# so that some schedules reach the target year with a full-year amount while
# others contribute their mid-month first-year (or a tail-year) amount. Recovery
# periods include the 27.5-year residential default plus a few shorter periods.
_asset_placed_dates = st.dates(
    min_value=dt.date(TAX_YEAR - 4, 1, 1),
    max_value=dt.date(TAX_YEAR, 12, 31),
).map(lambda d: d.isoformat())

_asset_cost_basis = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("500000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_asset_recovery_periods = st.sampled_from(
    [Decimal("27.5"), Decimal("5"), Decimal("7"), Decimal("15"), Decimal("39")]
)


@st.composite
def _asset_specs(draw):
    """A list of ``0..k`` (cost_basis, placed_in_service_date, recovery) specs."""
    n = draw(st.integers(min_value=0, max_value=4))
    specs: list[tuple[Decimal, str, Decimal]] = []
    for _ in range(n):
        specs.append(
            (
                draw(_asset_cost_basis),
                draw(_asset_placed_dates),
                draw(_asset_recovery_periods),
            )
        )
    return specs


# Transactions all fall within the target tax year, drawn freely across
# assignable income and expense categories -- never Line 18, which isn't
# assignable. Only Other/Line 19 requires a description.
_txn_dates_in_year = st.dates(
    min_value=dt.date(TAX_YEAR, 1, 1), max_value=dt.date(TAX_YEAR, 12, 31)
).map(lambda d: d.isoformat())

_txn_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_txn_category_ids = st.sampled_from(_INCOME_CATEGORY_IDS + _EXPENSE_CATEGORY_IDS)


@st.composite
def _transaction_specs(draw):
    """A list of ``0..k`` (category_id, date, amount, description) specs."""
    n = draw(st.integers(min_value=0, max_value=10))
    specs: list[tuple[str, str, Decimal, str | None]] = []
    for _ in range(n):
        category_id = draw(_txn_category_ids)
        date_str = draw(_txn_dates_in_year)
        amount = draw(_txn_amounts)
        description = None
        if _CATEGORY_BY_ID[category_id].requires_description:
            description = draw(
                st.text(min_size=1, max_size=20).filter(lambda s: s.strip())
            )
        specs.append((category_id, date_str, amount, description))
    return specs


# Feature: logstead, Property 22: Report depreciation line equals computed depreciation
@settings(deadline=None, max_examples=100)
@given(asset_specs=_asset_specs(), txn_specs=_transaction_specs())
def test_report_depreciation_line_equals_computed_depreciation(
    asset_specs: list[tuple[Decimal, str, Decimal]],
    txn_specs: list[tuple[str, str, Decimal, str | None]],
) -> None:
    """Report Line 18 == summed schedule depreciation, invariant to transactions.

    Validates: Requirements 10.3, 7.5
    """
    with _moto_service() as (report, properties, transactions, depreciation):
        created = properties.create(
            PropertyInput(
                name="Depreciation Subject",
                address_text="1 Depreciation Way",
                property_type="single_family",
            )
        )
        assert created.is_ok, created.error
        pid = created.value.id

        # Create the depreciable assets. Each create_asset materializes its
        # schedule. Compute the expected Line 18 total independently in the test
        # as the sum over assets of each asset's schedule amount for TAX_YEAR.
        expected_line_18 = Decimal("0.00")
        for cost_basis, placed_date, recovery in asset_specs:
            asset_result = depreciation.create_asset(
                AssetInput(
                    property_id=pid,
                    description="Asset",
                    cost_basis=cost_basis,
                    placed_in_service_date=placed_date,
                    recovery_period_years=recovery,
                )
            )
            assert asset_result.is_ok, asset_result.error
            asset_id = asset_result.value.id

            # Sum this asset's schedule row(s) for the target tax year directly
            # from schedule_for -- the ground truth Line 18 must equal.
            for row in depreciation.schedule_for(pid, asset_id):
                if row.tax_year == TAX_YEAR:
                    expected_line_18 += row.amount
        expected_line_18 = expected_line_18.quantize(Decimal("0.01"))

        # The service's own per-(property, year) figure must match the test's
        # independently summed schedule amounts.
        service_dep = depreciation.property_depreciation_for_year(pid, TAX_YEAR)
        assert service_dep == expected_line_18, (
            f"property_depreciation_for_year {service_dep} != "
            f"summed schedule amounts {expected_line_18}"
        )

        # Build the report BEFORE adding any transactions. Line 18 here reflects
        # the schedules alone.
        pre_txn = report.report_for(pid, TAX_YEAR)
        assert pre_txn.is_ok, pre_txn.error
        pre_txn_line_18 = pre_txn.value.line(DEPRECIATION_LINE).total

        # Add the user transactions across assignable (non-Line-18) categories.
        for category_id, date_str, amount, description in txn_specs:
            category = _CATEGORY_BY_ID[category_id]
            # Guard the invariant at the source: no assignable category is
            # Line 18 (Requirement 7.5).
            assert category.schedule_e_line != DEPRECIATION_LINE
            txn_result = transactions.create(
                TransactionInput(
                    property_id=pid,
                    date=date_str,
                    amount=amount,
                    type=category.kind,  # "income" | "expense"
                    category_id=category_id,
                    description=description,
                )
            )
            assert txn_result.is_ok, txn_result.error

        result = report.report_for(pid, TAX_YEAR)
        assert result.is_ok, result.error
        rpt = result.value
        line_18 = rpt.line(DEPRECIATION_LINE)
        assert line_18 is not None

        # (a) Line 18 == property_depreciation_for_year == summed schedule
        #     amounts for the year (Requirement 10.3).
        assert line_18.total == service_dep
        assert line_18.total == expected_line_18

        # (b) Line 18's kind is expense and it is included in total_expenses.
        assert line_18.kind == "expense"
        expense_line_sum = sum(
            (ln.total for ln in rpt.lines if ln.kind == "expense"),
            Decimal("0.00"),
        )
        assert rpt.totals.total_expenses == expense_line_sum
        # Removing Line 18 from the expense total drops it by exactly Line 18.
        expense_without_18 = sum(
            (
                ln.total
                for ln in rpt.lines
                if ln.kind == "expense" and ln.line != DEPRECIATION_LINE
            ),
            Decimal("0.00"),
        )
        assert rpt.totals.total_expenses - expense_without_18 == line_18.total

        # (c) Line 18 is invariant to the transactions: adding user income and
        #     expense transactions did not change it -- no transaction can
        #     contribute to Line 18 (Requirements 10.3, 7.5).
        assert line_18.total == pre_txn_line_18
