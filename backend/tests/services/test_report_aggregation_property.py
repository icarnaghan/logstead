"""Property-based test: report aggregation is correct and balances.

Design Property 21 (Requirements 10.1, 10.4): *for any* set of transactions for
a property and tax year, each Schedule E line total equals the sum of that
year's transactions assigned to that line, and the report's net income or loss
equals total income minus total expenses.

``ReportingService.report_for`` (``services/report.py``) aggregates a property's
in-year transactions onto their recorded Schedule E line. Income transactions
accumulate onto income lines (3-4), expense transactions onto expense lines
(5-17, 19). Line 18 (Depreciation) is **not** fed by transactions -- it comes
from the depreciation schedules -- so this test provisions **no depreciable
assets**, pinning Line 18 to ``0.00`` and keeping the property squarely on the
transaction-aggregation concern this property is about. ``total_expenses``
therefore reduces to the sum of the expense-line totals, and ``net`` is
``total_income - total_expenses`` exactly, in ``Decimal``.

The test drives this universally. It generates a random set of transactions --
varied categories spanning income and expense (including several assigned to the
Other/Line 19 category, which requires a description), varied positive
two-decimal amounts, and dates within a single target tax year -- for one
freshly created property. Expected per-line sums are computed **in the test**
from the created transactions grouped by their category's ``schedule_e_line``
(the same catalog the service reads), then compared against the report:

* (a) each Schedule E line total equals the summed amounts of the created
  transactions assigned to that line, excluding Line 18 (always ``0.00`` here);
* (b) ``total_income`` equals the sum of the income-line totals;
* (c) ``total_expenses`` equals the sum of the expense-line totals (Line 18
  included but zero, since no assets exist);
* (d) ``net == total_income - total_expenses`` exactly as a ``Decimal``.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 for the property meta mirror + GSI2 for the tax-year partition the
report reads through) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring the fixture pattern in ``test_report.py``.
Per-example provisioning is not instantaneous, so the deadline is disabled; the
example count is held at >= 100.
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

# The assignable catalog indexed by id, and the line/kind lookups the test uses
# to compute expected sums independently of the service. ``requires_description``
# tells the generator which categories (only Other/Line 19) must carry text.
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
    partition the report reads transactions through.
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
# Every transaction falls within the single target tax year, so all of them are
# in scope for ``report_for(pid, TAX_YEAR)``. Dates span all twelve months and
# both boundary days of the year.
_dates_in_year = st.dates(
    min_value=dt.date(TAX_YEAR, 1, 1), max_value=dt.date(TAX_YEAR, 12, 31)
).map(lambda d: d.isoformat())

# Positive two-decimal amounts, so the amount>0 rule always holds. Capped so a
# dozen transactions never overflow two-decimal money semantics.
_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Any assignable category id -- income or expense, including Other (Line 19).
_category_ids = st.sampled_from(
    _INCOME_CATEGORY_IDS + _EXPENSE_CATEGORY_IDS
)


@st.composite
def _transaction_specs(draw):
    """A non-empty list of (category_id, date, amount, description) specs.

    Categories are drawn freely across income and expense lines so several lines
    accumulate multiple transactions (and some none). Only the Other category
    requires a description (Requirement 7.4); every other category omits it. The
    ``type`` a transaction is created with is derived from the category kind so
    creation always succeeds.
    """
    n = draw(st.integers(min_value=1, max_value=12))
    specs: list[tuple[str, str, Decimal, str | None]] = []
    for i in range(n):
        category_id = draw(_category_ids)
        date_str = draw(_dates_in_year)
        amount = draw(_amounts)
        description = None
        if _CATEGORY_BY_ID[category_id].requires_description:
            description = draw(
                st.text(min_size=1, max_size=20).filter(lambda s: s.strip())
            )
        specs.append((category_id, date_str, amount, description))
    return specs


# Feature: logstead, Property 21: Report aggregation is correct and balances
@settings(deadline=None, max_examples=120)
@given(specs=_transaction_specs())
def test_report_aggregation_is_correct_and_balances(
    specs: list[tuple[str, str, Decimal, str | None]],
) -> None:
    """Each line total equals its transactions' sum; net balances (Decimal).

    Validates: Requirements 10.1, 10.4
    """
    with _moto_service() as (report, properties, transactions, _depreciation):
        created = properties.create(
            PropertyInput(
                name="Aggregation Subject",
                address_text="1 Aggregation Way",
                property_type="single_family",
            )
        )
        assert created.is_ok, created.error
        pid = created.value.id

        # Create every generated transaction and, in parallel, accumulate the
        # expected per-line total independently of the service -- grouping each
        # amount by its category's Schedule E line (the same static catalog the
        # service resolves from at create time).
        expected_line_totals: dict[int, Decimal] = {}
        for category_id, date_str, amount, description in specs:
            category = _CATEGORY_BY_ID[category_id]
            result = transactions.create(
                TransactionInput(
                    property_id=pid,
                    date=date_str,
                    amount=amount,
                    type=category.kind,  # "income" | "expense"
                    category_id=category_id,
                    description=description,
                )
            )
            assert result.is_ok, result.error
            line = category.schedule_e_line
            expected_line_totals[line] = (
                expected_line_totals.get(line, Decimal("0.00")) + amount
            )

        result = report.report_for(pid, TAX_YEAR)
        assert result.is_ok, result.error
        rpt = result.value

        # No depreciable assets were created, so Line 18 must be exactly zero
        # and is excluded from the transaction-driven per-line assertions.
        assert rpt.line(DEPRECIATION_LINE).total == Decimal("0.00")

        # (a) Each Schedule E line total equals the summed amounts of the
        #     created transactions assigned to that line (Requirement 10.1).
        #     Lines with no transactions must report 0.00.
        for report_line in rpt.lines:
            if report_line.line == DEPRECIATION_LINE:
                continue
            expected = expected_line_totals.get(
                report_line.line, Decimal("0.00")
            )
            assert report_line.total == expected, (
                f"line {report_line.line}: report {report_line.total} != "
                f"expected {expected}"
            )

        # (b) total_income == sum of income-line totals (Requirement 10.4).
        expected_income = sum(
            (ln.total for ln in rpt.lines if ln.kind == "income"),
            Decimal("0.00"),
        )
        assert rpt.totals.total_income == expected_income

        # (c) total_expenses == sum of expense-line totals, Line 18 included
        #     (== 0.00 here since there are no assets) (Requirement 10.4).
        expected_expenses = sum(
            (ln.total for ln in rpt.lines if ln.kind == "expense"),
            Decimal("0.00"),
        )
        assert rpt.totals.total_expenses == expected_expenses

        # (d) net == total_income - total_expenses, exact Decimal
        #     (Requirement 10.4).
        assert rpt.totals.net == (
            rpt.totals.total_income - rpt.totals.total_expenses
        )
