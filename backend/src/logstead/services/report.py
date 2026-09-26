"""Schedule E Report Service (Requirement 10).

This service produces the year-end Schedule E (Form 1040) summary for a single
property and the combined portfolio report across all of a user's properties.
Everything is **derived from persisted data alone** — transactions, depreciation
schedules, and per-year usage days — so a report is always reproducible from
stored records with no cached aggregates (Requirement 12.5).

What a per-property report contains
-----------------------------------
``report_for(property_id, tax_year)`` produces a :class:`ScheduleEReport`:

* a :class:`ReportHeader` carrying the property name, address, property type,
  tax year, and the stored fair-rental / personal-use days (Requirement 10.2);
* one :class:`ReportLine` for **every** Schedule E Part I line that Logstead
  models — income lines 3-4, expense lines 5-17, Line 18 Depreciation, and
  Line 19 Other — each with the two-decimal total for that line
  (Requirement 10.1). Income lines total income transactions, expense lines
  total expense transactions, and **Line 18 comes from the depreciation
  schedules** (:meth:`DepreciationService.property_depreciation_for_year`),
  not from any transaction category (Requirements 10.3, 7.5);
* the Line 19 Other total is **itemized**: each Other-category transaction
  appears as an :class:`OtherItem` (description + amount), and those amounts
  reconcile to the Line 19 total (Requirements 10.5, 10.6-as-itemization);
* ``total_income``, ``total_expenses`` (which **includes** the Line 18
  depreciation), and ``net`` = total income - total expenses
  (Requirement 10.4).

What a combined report contains
-------------------------------
``combined_report(property_ids | None, tax_year)`` produces a
:class:`CombinedScheduleEReport`: one per-property :class:`ScheduleEReport`
column plus a portfolio :class:`ReportTotals` column whose income/expense/net
equal the sums of the per-property values (Requirement 10.6). When
``property_ids`` is ``None`` every property the injected
:class:`PropertyService` can list for the user is included.

Aggregation model
------------------
Each transaction contributes its amount to the Schedule E line recorded on it
(``transaction.schedule_e_line``, set at create time from its category). Income
transactions accumulate onto income lines; expense transactions accumulate onto
expense lines. Line 18 is never fed by transactions — it is read from the
materialized depreciation schedule for the (property, year). ``net`` is
``total_income - total_expenses`` with expenses inclusive of Line 18. Line rows
are emitted in ascending Schedule E line order so the report is deterministic
for identical inputs.

Collaborators are injected (transaction, depreciation, and property services)
so the whole service can be exercised against ``moto`` with no live AWS call.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from logstead.adapters.s3_files import export_key
from logstead.models.result import Result
from logstead.services.category import CATEGORY_CATALOG
from logstead.util.money import Money, money_to_str, to_money

if TYPE_CHECKING:
    from logstead.adapters.s3_files import S3FileAdapter
    from logstead.services.depreciation import DepreciationService
    from logstead.services.property import PropertyService
    from logstead.services.transaction import TransactionService


__all__ = [
    "DEPRECIATION_LINE",
    "OTHER_LINE",
    "SCHEDULE_E_LINE_LABELS",
    "OtherItem",
    "ReportLine",
    "ReportHeader",
    "ReportTotals",
    "ScheduleEReport",
    "CombinedScheduleEReport",
    "ExportFormat",
    "ReportExport",
    "ReportingService",
]

#: The export formats the report service can serialize to (Requirement 10.7).
ExportFormat = Literal["csv", "json"]


# --- Schedule E line reference ----------------------------------------------
#
# The set of Schedule E Part I lines Logstead models, in form order. Income
# lines (3, 4) and expense lines (5-17, 19) come from the seeded category
# catalog; Line 18 (Depreciation) is not an assignable category (Requirement
# 7.5) and is derived from the depreciation schedules (Requirement 10.3), so we
# add it explicitly here.

#: Schedule E Line 18 — Depreciation. Populated from depreciation schedules, not
#: from transactions (Requirements 7.5, 10.3).
DEPRECIATION_LINE: int = 18

#: Schedule E Line 19 — Other expenses. Itemized in the report (Requirement 10.5).
OTHER_LINE: int = 19

# Human-readable labels per line, taken from the category catalog plus the
# derived depreciation line. Income lines carry their catalog label; expense
# lines likewise; Line 18 is labeled "Depreciation expense or depletion".
_INCOME_LINES: frozenset[int] = frozenset(
    c.schedule_e_line for c in CATEGORY_CATALOG if c.kind == "income"
)

SCHEDULE_E_LINE_LABELS: dict[int, str] = {
    **{c.schedule_e_line: c.label for c in CATEGORY_CATALOG},
    DEPRECIATION_LINE: "Depreciation expense or depletion",
}

# The full ordered set of lines a report renders: every catalog line plus the
# depreciation line, ascending.
_ALL_LINES: tuple[int, ...] = tuple(sorted(SCHEDULE_E_LINE_LABELS))


def _is_income_line(line: int) -> bool:
    """True for Schedule E income lines (Rents/Royalties, lines 3-4)."""
    return line in _INCOME_LINES


# --- Report data shapes ------------------------------------------------------


@dataclass(frozen=True)
class OtherItem:
    """One itemized Line 19 "Other" expense (Requirement 10.5).

    Attributes:
        description: The transaction's free-text description (required for the
            Other category, Requirement 7.4).
        amount: The transaction amount as a two-decimal ``Decimal``.
    """

    description: str
    amount: Money


@dataclass(frozen=True)
class ReportLine:
    """A single Schedule E line total on a report (Requirement 10.1).

    Attributes:
        line: The Schedule E Part I line number.
        label: Human-readable line label.
        kind: ``"income"`` or ``"expense"`` — whether the line contributes to
            total income or total expenses.
        total: The two-decimal total for the line.
    """

    line: int
    label: str
    kind: str
    total: Money


@dataclass(frozen=True)
class ReportHeader:
    """The Schedule E report header for a property + tax year (Requirement 10.2).

    Attributes:
        property_id: The property this report is for.
        property_name: The property's display name.
        address: The property's address text.
        property_type: The property type, if recorded.
        tax_year: The tax year the report covers.
        fair_rental_days: Stored fair-rental days for the year (``0`` if unset).
        personal_use_days: Stored personal-use days for the year (``0`` if unset).
    """

    property_id: str
    property_name: str
    address: str
    property_type: str | None
    tax_year: int
    fair_rental_days: int
    personal_use_days: int


@dataclass(frozen=True)
class ReportTotals:
    """Income / expense / net totals for a property or the portfolio (10.4, 10.6).

    Attributes:
        total_income: Sum of income-line totals.
        total_expenses: Sum of expense-line totals, **including** Line 18
            depreciation.
        net: ``total_income - total_expenses`` (may be negative — a loss).
    """

    total_income: Money
    total_expenses: Money
    net: Money


@dataclass(frozen=True)
class ScheduleEReport:
    """A per-property Schedule E report (Requirements 10.1-10.5).

    Attributes:
        header: The report header (property + usage days).
        lines: One :class:`ReportLine` per modeled Schedule E line, ascending.
        other_items: Itemized Line 19 "Other" expenses (Requirement 10.5).
        totals: Income / expense / net totals (Requirement 10.4).
    """

    header: ReportHeader
    lines: tuple[ReportLine, ...]
    other_items: tuple[OtherItem, ...]
    totals: ReportTotals

    def line(self, number: int) -> ReportLine | None:
        """Return the :class:`ReportLine` for a given line number, if present."""
        for row in self.lines:
            if row.line == number:
                return row
        return None


@dataclass(frozen=True)
class CombinedScheduleEReport:
    """A portfolio report combining several properties (Requirement 10.6).

    Attributes:
        tax_year: The tax year the combined report covers.
        properties: One per-property :class:`ScheduleEReport` column, in the
            order the properties were supplied / listed.
        totals: The portfolio totals column, equal to the sums of the
            per-property totals.
    """

    tax_year: int
    properties: tuple[ScheduleEReport, ...]
    totals: ReportTotals


@dataclass(frozen=True)
class ReportExport:
    """A serialized, downloadable report file (Requirement 10.7).

    Attributes:
        key: The S3 object key the export was stored under (``exports/...``).
        filename: The suggested download filename.
        content_type: The MIME type of the serialized file.
        content: The raw serialized bytes (also written to S3).
        download_url: A pre-signed GET URL the browser can download from.
    """

    key: str
    filename: str
    content_type: str
    content: bytes
    download_url: str


# --- Serialization -----------------------------------------------------------
#
# A report serializes with money rendered as fixed two-decimal strings so the
# on-the-wire/file representation never drifts (Requirement 13.3). CSV lays the
# Schedule E line table out as rows the way the form reads; JSON mirrors the
# report's structure for machine consumption.

_CONTENT_TYPES: dict[str, str] = {
    "csv": "text/csv",
    "json": "application/json",
}


def _report_to_csv(report: ScheduleEReport) -> bytes:
    """Serialize a per-property report to a Schedule E CSV table.

    Header rows carry the property / tax-year / usage days; a line table
    (``line, label, kind, amount``) follows; then the Line 19 "Other"
    itemization; then the income / expense / net totals. Money renders as
    fixed two-decimal strings.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    h = report.header
    writer.writerow(["Schedule E Report"])
    writer.writerow(["Property", h.property_name])
    writer.writerow(["Address", h.address])
    writer.writerow(["Property Type", h.property_type or ""])
    writer.writerow(["Tax Year", h.tax_year])
    writer.writerow(["Fair Rental Days", h.fair_rental_days])
    writer.writerow(["Personal Use Days", h.personal_use_days])
    writer.writerow([])

    writer.writerow(["Line", "Label", "Kind", "Amount"])
    for row in report.lines:
        writer.writerow([row.line, row.label, row.kind, money_to_str(row.total)])
    writer.writerow([])

    writer.writerow(["Other (Line 19) Itemization"])
    writer.writerow(["Description", "Amount"])
    for item in report.other_items:
        writer.writerow([item.description, money_to_str(item.amount)])
    writer.writerow([])

    writer.writerow(["Total Income", money_to_str(report.totals.total_income)])
    writer.writerow(["Total Expenses", money_to_str(report.totals.total_expenses)])
    writer.writerow(["Net", money_to_str(report.totals.net)])

    return buf.getvalue().encode("utf-8")


def _totals_dict(totals: ReportTotals) -> dict:
    return {
        "total_income": money_to_str(totals.total_income),
        "total_expenses": money_to_str(totals.total_expenses),
        "net": money_to_str(totals.net),
    }


def _report_dict(report: ScheduleEReport) -> dict:
    h = report.header
    return {
        "header": {
            "property_id": h.property_id,
            "property_name": h.property_name,
            "address": h.address,
            "property_type": h.property_type,
            "tax_year": h.tax_year,
            "fair_rental_days": h.fair_rental_days,
            "personal_use_days": h.personal_use_days,
        },
        "lines": [
            {
                "line": row.line,
                "label": row.label,
                "kind": row.kind,
                "amount": money_to_str(row.total),
            }
            for row in report.lines
        ],
        "other_items": [
            {"description": item.description, "amount": money_to_str(item.amount)}
            for item in report.other_items
        ],
        "totals": _totals_dict(report.totals),
    }


def _report_to_json(report: ScheduleEReport) -> bytes:
    return json.dumps(_report_dict(report), indent=2).encode("utf-8")


def _combined_to_csv(report: CombinedScheduleEReport) -> bytes:
    """Serialize a combined report: one Schedule E block per property, then the
    portfolio totals column. Money renders as fixed two-decimal strings."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Combined Schedule E Report"])
    writer.writerow(["Tax Year", report.tax_year])
    writer.writerow([])

    for column in report.properties:
        # Reuse the per-property CSV block, indenting each as its own section.
        block = _report_to_csv(column).decode("utf-8")
        buf.write(block)
        if not block.endswith("\n"):
            buf.write("\n")
        buf.write("\n")

    writer.writerow(["Portfolio Totals"])
    writer.writerow(["Total Income", money_to_str(report.totals.total_income)])
    writer.writerow(["Total Expenses", money_to_str(report.totals.total_expenses)])
    writer.writerow(["Net", money_to_str(report.totals.net)])
    return buf.getvalue().encode("utf-8")


def _combined_to_json(report: CombinedScheduleEReport) -> bytes:
    payload = {
        "tax_year": report.tax_year,
        "properties": [_report_dict(c) for c in report.properties],
        "totals": _totals_dict(report.totals),
    }
    return json.dumps(payload, indent=2).encode("utf-8")


# --- Service -----------------------------------------------------------------


class ReportingService:
    """Builds per-property and combined Schedule E reports (Requirement 10).

    Args:
        transactions: The transaction service, used to read a property's
            tax-year transactions (already ordered; order does not matter for
            aggregation).
        depreciation: The depreciation service, used for the Line 18 total via
            :meth:`DepreciationService.property_depreciation_for_year`.
        properties: The property service, used for the header (name/address/
            type), usage days, and — for the combined report — the user's
            property list.
        files: The S3 file adapter, used by :meth:`export_report` /
            :meth:`export_combined_report` to store the generated export under
            the ``exports/`` prefix and issue a pre-signed download URL. May be
            omitted when only report generation (not export) is needed.
    """

    def __init__(
        self,
        transactions: "TransactionService",
        depreciation: "DepreciationService",
        properties: "PropertyService",
        files: "S3FileAdapter | None" = None,
    ) -> None:
        self._transactions = transactions
        self._depreciation = depreciation
        self._properties = properties
        self._files = files

    # --- Per-property report (Requirements 10.1-10.5) -----------------------

    def report_for(
        self, property_id: str, tax_year: int
    ) -> Result[ScheduleEReport]:
        """Build the Schedule E report for one property + tax year.

        Aggregates the property's in-year transactions into per-line totals
        (Requirement 10.1), fills Line 18 from the depreciation schedules
        (Requirement 10.3), itemizes Line 19 "Other" (Requirement 10.5), and
        computes total income, total expenses, and net (Requirement 10.4). The
        header carries the property's address / type and the stored fair-rental
        and personal-use days (Requirement 10.2).

        Returns ``not_found`` if the property does not exist or is not owned by
        the service's user.
        """
        prop_result = self._properties.get(property_id)
        if not prop_result.is_ok:
            # Propagate not_found (or whatever the property service reported).
            return Result.failure(
                prop_result.error.kind,
                prop_result.error.message,
                prop_result.error.field,
            )
        prop = prop_result.value

        report = self._build_report(
            property_id=property_id,
            property_name=prop.name,
            address=prop.address_text,
            property_type=prop.property_type,
            tax_year=tax_year,
        )
        return Result.success(report)

    # --- Combined portfolio report (Requirement 10.6) -----------------------

    def combined_report(
        self, property_ids: list[str] | None, tax_year: int
    ) -> Result[CombinedScheduleEReport]:
        """Build the combined portfolio report for a tax year.

        When ``property_ids`` is ``None``, every property the injected property
        service lists for the user is included; otherwise exactly the given
        properties (each must exist / be owned). Produces a per-property column
        for each and a portfolio totals column equal to the sum of the
        per-property income, expense, and net values (Requirement 10.6).

        Returns ``not_found`` if any explicitly requested property is missing.
        """
        if property_ids is None:
            ordered = [p.id for p in self._properties.list()]
        else:
            ordered = list(property_ids)

        columns: list[ScheduleEReport] = []
        for pid in ordered:
            sub = self.report_for(pid, tax_year)
            if not sub.is_ok:
                return Result.failure(
                    sub.error.kind, sub.error.message, sub.error.field
                )
            columns.append(sub.value)

        totals = self._portfolio_totals(columns)
        return Result.success(
            CombinedScheduleEReport(
                tax_year=tax_year,
                properties=tuple(columns),
                totals=totals,
            )
        )

    # --- Export (Requirement 10.7) ------------------------------------------

    def export_report(
        self, property_id: str, tax_year: int, format: ExportFormat = "csv"
    ) -> Result[ReportExport]:
        """Generate a per-property report, serialize it, and store it for download.

        Builds the Schedule E report for ``property_id`` + ``tax_year`` (same
        data path as :meth:`report_for`), serializes it to CSV or JSON with
        money rendered as fixed two-decimal strings (Requirement 13.3), writes
        the bytes to S3 under ``exports/<property_id>/<tax_year>/<filename>``,
        and returns a :class:`ReportExport` carrying the raw bytes and a
        pre-signed GET URL for download (Requirement 10.7).

        Returns ``validation`` if ``format`` is unsupported, ``not_found`` if
        the property is missing, and ``unavailable`` if no file adapter was
        configured on the service.
        """
        fmt_error = self._validate_format(format)
        if fmt_error is not None:
            return fmt_error
        if self._files is None:
            return Result.failure(
                "unavailable", "Export is not available (no file store configured)."
            )

        report_result = self.report_for(property_id, tax_year)
        if not report_result.is_ok:
            return Result.failure(
                report_result.error.kind,
                report_result.error.message,
                report_result.error.field,
            )
        report = report_result.value

        if format == "json":
            content = _report_to_json(report)
        else:
            content = _report_to_csv(report)

        filename = f"schedule-e-{tax_year}.{format}"
        key = export_key(property_id, str(tax_year), filename)
        return Result.success(self._store_export(key, filename, format, content))

    def export_combined_report(
        self,
        property_ids: list[str] | None,
        tax_year: int,
        format: ExportFormat = "csv",
    ) -> Result[ReportExport]:
        """Generate the combined portfolio report, serialize it, and store it.

        Mirrors :meth:`export_report` for the combined report
        (Requirement 10.6): the export lands under
        ``exports/combined/<tax_year>/<filename>`` and a pre-signed GET URL is
        returned (Requirement 10.7).
        """
        fmt_error = self._validate_format(format)
        if fmt_error is not None:
            return fmt_error
        if self._files is None:
            return Result.failure(
                "unavailable", "Export is not available (no file store configured)."
            )

        combined_result = self.combined_report(property_ids, tax_year)
        if not combined_result.is_ok:
            return Result.failure(
                combined_result.error.kind,
                combined_result.error.message,
                combined_result.error.field,
            )
        combined = combined_result.value

        if format == "json":
            content = _combined_to_json(combined)
        else:
            content = _combined_to_csv(combined)

        filename = f"schedule-e-combined-{tax_year}.{format}"
        key = export_key("combined", str(tax_year), filename)
        return Result.success(self._store_export(key, filename, format, content))

    @staticmethod
    def _validate_format(format: str) -> "Result[ReportExport] | None":
        """Return a validation failure Result for an unsupported format, else None."""
        if format not in _CONTENT_TYPES:
            return Result.failure(
                "validation",
                f"Unsupported export format '{format}'. Use 'csv' or 'json'.",
                "format",
            )
        return None

    def _store_export(
        self, key: str, filename: str, format: str, content: bytes
    ) -> ReportExport:
        """Write the serialized export to S3 and return it with a download URL."""
        content_type = _CONTENT_TYPES[format]
        assert self._files is not None  # guarded by callers
        self._files.put_object(key, content, content_type)
        download_url = self._files.presigned_get_url(key)
        return ReportExport(
            key=key,
            filename=filename,
            content_type=content_type,
            content=content,
            download_url=download_url,
        )

    # --- Internals -----------------------------------------------------------

    def _build_report(
        self,
        property_id: str,
        property_name: str,
        address: str,
        property_type: str | None,
        tax_year: int,
    ) -> ScheduleEReport:
        """Aggregate persisted data into a :class:`ScheduleEReport`.

        Pure aggregation: sum in-year transactions onto their recorded Schedule
        E lines, pull Line 18 from depreciation, itemize Line 19, then derive
        totals and net. Deterministic for identical persisted inputs.
        """
        # Per-line running totals, seeded to 0.00 for every modeled line so the
        # report always renders a full, stable set of lines even when a line has
        # no activity.
        line_totals: dict[int, Decimal] = {
            line: Decimal("0.00") for line in _ALL_LINES
        }
        other_items: list[OtherItem] = []

        txn_result = self._transactions.list_for_property(property_id, tax_year)
        # list_for_property always returns a success list here.
        for txn in txn_result.value:
            line = int(txn.schedule_e_line)
            amount = to_money(txn.amount)
            # Defensive: only accumulate onto lines the report models. A stored
            # depreciation line (18) never comes from a transaction, but guard
            # anyway so a stray value can't double-count against Line 18.
            if line == DEPRECIATION_LINE:
                continue
            line_totals[line] = line_totals.get(line, Decimal("0.00")) + amount

            if line == OTHER_LINE:
                other_items.append(
                    OtherItem(
                        description=(txn.description or ""),
                        amount=amount,
                    )
                )

        # Line 18 comes from the depreciation schedules (Requirement 10.3).
        line_totals[DEPRECIATION_LINE] = self._depreciation.property_depreciation_for_year(
            property_id, tax_year
        )

        lines = tuple(
            ReportLine(
                line=line,
                label=SCHEDULE_E_LINE_LABELS[line],
                kind="income" if _is_income_line(line) else "expense",
                total=to_money(line_totals[line]),
            )
            for line in _ALL_LINES
        )

        totals = self._totals_from_lines(lines)
        header = self._header(
            property_id, property_name, address, property_type, tax_year
        )
        return ScheduleEReport(
            header=header,
            lines=lines,
            other_items=tuple(other_items),
            totals=totals,
        )

    def _header(
        self,
        property_id: str,
        property_name: str,
        address: str,
        property_type: str | None,
        tax_year: int,
    ) -> ReportHeader:
        """Build the report header, reading stored usage days (Requirement 10.2).

        When no usage-year record exists for the property + year, both day
        counts default to ``0`` so the header is always complete.
        """
        fair_rental_days = 0
        personal_use_days = 0
        usage = self._properties.get_usage_days(property_id, tax_year)
        if usage.is_ok:
            fair_rental_days = usage.value.fair_rental_days
            personal_use_days = usage.value.personal_use_days
        return ReportHeader(
            property_id=property_id,
            property_name=property_name,
            address=address,
            property_type=property_type,
            tax_year=tax_year,
            fair_rental_days=fair_rental_days,
            personal_use_days=personal_use_days,
        )

    @staticmethod
    def _totals_from_lines(lines: tuple[ReportLine, ...]) -> ReportTotals:
        """Sum income/expense line totals and derive net (Requirement 10.4).

        Total expenses include Line 18 depreciation (its line kind is expense).
        Net is total income minus total expenses and may be negative (a loss).
        """
        total_income = Decimal("0.00")
        total_expenses = Decimal("0.00")
        for row in lines:
            if row.kind == "income":
                total_income += row.total
            else:
                total_expenses += row.total
        total_income = to_money(total_income)
        total_expenses = to_money(total_expenses)
        return ReportTotals(
            total_income=total_income,
            total_expenses=total_expenses,
            net=to_money(total_income - total_expenses),
        )

    @staticmethod
    def _portfolio_totals(columns: list[ScheduleEReport]) -> ReportTotals:
        """Sum per-property totals into the portfolio totals column (10.6)."""
        total_income = Decimal("0.00")
        total_expenses = Decimal("0.00")
        for report in columns:
            total_income += report.totals.total_income
            total_expenses += report.totals.total_expenses
        total_income = to_money(total_income)
        total_expenses = to_money(total_expenses)
        return ReportTotals(
            total_income=total_income,
            total_expenses=total_expenses,
            net=to_money(total_income - total_expenses),
        )
