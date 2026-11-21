"""Property-based test: Schedule E Import round-trip reconciliation.

Design Property 2 (schedule-e-import): *for any* valid Import_Submission (one
Tax_Year, one or more Property_Entries each with at least one non-zero
two-decimal line amount), after ``import_schedule_e`` the derived
``ReportingService.report_for(property, tax_year)`` line total for each entered
line equals the entered amount quantized to two decimals (and ``0.00`` for a
line that was not entered), and a combined/portfolio total equals the exact sum
of the per-property line totals -- no precision drift.

Because Logstead **derives** Schedule E reports from stored transactions, the
import synthesizes one backing transaction per non-zero line; the report then
re-aggregates them. This test closes that loop: it generates the entered
amounts, drives them through ``ImportService.import_schedule_e``, reads them
back through ``ReportingService``, and asserts the per-line totals reconcile to
the two-decimal-quantized entered amounts with no drift, and that the portfolio
totals equal the exact sum of the per-property totals.

Lines the catalog models are the income lines 3-4 and the expense lines 5-17
and 19 (Line 18 Depreciation is deliberately not an assignable line and is fed
only by depreciation schedules; no depreciable assets are created here, so Line
18 stays ``0.00`` for every property and never contributes).

Each entry maps to a distinct owned property, created in the test. Money is
generated with Hypothesis ``decimals`` quantized to two places and strictly
positive, so the amount>0 synthesis rule always holds and every generated line
is non-zero. Each Hypothesis example provisions its own moto-backed single
table (base + GSI1 for the property meta mirror + GSI2 for the tax-year
partition the report reads through) plus an S3 bucket, mirroring the fixture
pattern in ``test_schedule_e_import_service.py`` and
``test_report_aggregation_property.py``. Per-example provisioning is not
instantaneous, so the deadline is disabled; the example count is held at 100.
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
from logstead.models.schedule_e_import import (
    ImportSubmission,
    LineAmountInput,
    PropertyEntryInput,
)
from logstead.models.user import UserContext
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import DEPRECIATION_LINE, ReportingService
from logstead.services.schedule_e_import import ImportService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-roundtrip"

# The Schedule E lines a submission may carry: income 3-4, expenses 5-17 and 19.
# Line 18 (Depreciation) is intentionally absent from the catalog and is never
# entered or synthesized.
_ENTERABLE_LINES: tuple[int, ...] = (3, 4) + tuple(range(5, 18)) + (19,)


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields ``(ImportService, ReportingService, PropertyService)`` bound to
    freshly created resources so each Hypothesis example runs against a clean
    store. GSI1 is required by ``PropertyService.create`` (property meta
    mirror); GSI2 is the tax-year partition both the import's replace scan and
    the report read transactions through.
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
        imports = ImportService(repo, UserContext(user_id=USER), files)
        report = ReportingService(transactions, depreciation, properties)
        yield imports, report, properties


# --- Strategies --------------------------------------------------------------

# Strictly positive two-decimal money, so every generated line is non-zero and
# the amount>0 synthesis rule always holds. Capped so a handful of lines across
# a few properties never overflow two-decimal money semantics.
_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_tax_years = st.integers(min_value=2000, max_value=2099)


@st.composite
def _entry_line_maps(draw):
    """A non-empty list of per-property line->amount maps.

    Each map represents one Property_Entry: a non-empty subset of the enterable
    Schedule E lines, each assigned a strictly positive two-decimal amount. Each
    map is independent, so the entries can overlap on lines (that is fine --
    each maps to a *distinct* property). ``line 19`` carries a description in the
    test, applied at submission build time.
    """
    n_entries = draw(st.integers(min_value=1, max_value=3))
    entry_maps: list[dict[int, Decimal]] = []
    for _ in range(n_entries):
        lines = draw(
            st.lists(
                st.sampled_from(_ENTERABLE_LINES),
                min_size=1,
                max_size=len(_ENTERABLE_LINES),
                unique=True,
            )
        )
        line_map = {line: draw(_amounts) for line in lines}
        entry_maps.append(line_map)
    return entry_maps


def _two_dp(value: Decimal) -> Decimal:
    """Quantize a Decimal to two places (the money representation)."""
    return value.quantize(Decimal("0.01"))


# Feature: schedule-e-import, Property 2: round-trip reconciliation — entered lines reproduce report line totals with no drift
@settings(deadline=None, max_examples=100)
@given(tax_year=_tax_years, entry_maps=_entry_line_maps())
def test_round_trip_reconciliation_entered_lines_reproduce_report_totals(
    tax_year: int,
    entry_maps: list[dict[int, Decimal]],
) -> None:
    """Entered lines reproduce report line totals with no precision drift.

    Validates: Requirements 1.5, 3.1, 3.3, 10.2, 11.1, 11.2, 11.3
    """
    with _moto_service() as (imports, report, properties):
        # Each entry maps to a distinct freshly created, owned property.
        entries: list[PropertyEntryInput] = []
        property_ids: list[str] = []
        for i, line_map in enumerate(entry_maps):
            created = properties.create(
                PropertyInput(
                    name=f"Roundtrip Property {i}",
                    address_text=f"{i} Reconcile Way",
                    property_type="single_family",
                )
            )
            assert created.is_ok, created.error
            property_ids.append(created.value.id)

            lines = [
                LineAmountInput(
                    schedule_e_line=line,
                    amount=str(amount),
                    description="Imported other" if line == 19 else None,
                )
                for line, amount in line_map.items()
            ]
            entries.append(
                PropertyEntryInput(property_id=created.value.id, lines=lines)
            )

        result = imports.import_schedule_e(
            ImportSubmission(tax_year=tax_year, entries=entries)
        )
        assert result.is_ok, result.error

        # Per-property round-trip: every entered line's report total equals the
        # two-decimal-quantized entered amount; every non-entered modeled line
        # (except Line 18) reports 0.00; Line 18 is always 0.00 (no assets).
        per_property_income: list[Decimal] = []
        per_property_expenses: list[Decimal] = []
        for property_id, line_map in zip(property_ids, entry_maps):
            rpt_result = report.report_for(property_id, tax_year)
            assert rpt_result.is_ok, rpt_result.error
            rpt = rpt_result.value

            expected = {line: _two_dp(amount) for line, amount in line_map.items()}

            assert rpt.line(DEPRECIATION_LINE).total == Decimal("0.00")

            for report_line in rpt.lines:
                if report_line.line == DEPRECIATION_LINE:
                    continue
                want = expected.get(report_line.line, Decimal("0.00"))
                assert report_line.total == want, (
                    f"property {property_id} line {report_line.line}: "
                    f"report {report_line.total} != entered {want}"
                )

            per_property_income.append(rpt.totals.total_income)
            per_property_expenses.append(rpt.totals.total_expenses)

        # Portfolio totals equal the exact sum of the per-property line totals,
        # with no precision drift (Req 11.2, 11.3). Build the combined report
        # over exactly these properties and compare to the independent sum.
        combined_result = report.combined_report(property_ids, tax_year)
        assert combined_result.is_ok, combined_result.error
        combined = combined_result.value

        expected_income = sum(per_property_income, Decimal("0.00"))
        expected_expenses = sum(per_property_expenses, Decimal("0.00"))

        assert combined.totals.total_income == expected_income
        assert combined.totals.total_expenses == expected_expenses
        assert combined.totals.net == (expected_income - expected_expenses)
