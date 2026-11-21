"""Year-end checklist: models and pure helpers.

This module holds the immutable models of the checklist and the pure helper
functions the rules use. It performs no I/O and uses ``Decimal`` for every
amount. The rule functions and the gatherer service are added by later tasks.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, Protocol, get_args

from logstead.models.result import Result
from logstead.models.transaction import Transaction
from logstead.models.user import UserContext
from logstead.services.carryforward import (
    CarryforwardService,
    ReconciledYear,
    ReconciliationSummary,
)
from logstead.services.checklist_config import (
    CHECKLIST_CONFIG,
    AppliedThresholds,
    ChecklistConfig,
)
from logstead.services.dashboard import derive_data_years, latest_tax_year
from logstead.services.depreciation import DepreciationService
from logstead.services.itemized import CategoryRows, resolve_category_rows
from logstead.services.loan import LoanService, StoredLoanError
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService, ScheduleEReport
from logstead.services.transaction import TransactionService
from logstead.util.money import Money, to_money

ItemId = Literal[
    "income_entered",
    "expenses_entered",
    "depreciation_present",
    "line12_source",
    "loan_interest_confirmed",
    "carryforward_reconciled",
    "repairs_exceed_total",
    "repairs_capital_candidates",
    "receipts_missing",
    "yoy_swings",
    "imported_values_edited",
]

#: Fixed response order of the eleven items.
ITEM_IDS: tuple[ItemId, ...] = get_args(ItemId)

Status = Literal["done", "needs_attention", "not_applicable"]

#: Display limit for ``receipts_missing`` details (not a threshold).
MAX_RECEIPT_DETAILS = 25

#: Property page segments whose links carry ``?year=``.
_YEAR_SEGMENTS = frozenset({"transactions", "repairs", "reports"})

_ONE_TENTH = Decimal("0.1")
_CENTS = Decimal("0.01")
_HUNDRED = Decimal("100")
_ZERO = Decimal("0")


@dataclass(frozen=True)
class ChecklistItem:
    id: ItemId
    title: str
    status: Status
    reason: str
    link: str
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class ChecklistCounts:
    done: int
    needs_attention: int
    not_applicable: int
    total: int


@dataclass(frozen=True)
class Checklist:
    property_id: str
    tax_year: int
    items: tuple[ChecklistItem, ...]
    counts: ChecklistCounts
    thresholds: AppliedThresholds


@dataclass(frozen=True)
class ChecklistSummary:
    """Counts for one tax year, without the items."""

    tax_year: int
    counts: ChecklistCounts


@dataclass(frozen=True)
class PropertyChecklistSummary:
    """Property page summary: the most recent years, newest first."""

    property_id: str
    years: tuple[ChecklistSummary, ...]


@dataclass(frozen=True)
class PropertyChecklistRow:
    """One dashboard card row."""

    property_id: str
    property_name: str
    counts: ChecklistCounts


@dataclass(frozen=True)
class PortfolioChecklistSummary:
    tax_year: int
    properties: tuple[PropertyChecklistRow, ...]


@dataclass(frozen=True)
class LoanFact:
    """One loan's facts for the tax year (mirrors ``LoanYearFact``)."""

    loan_id: str
    description: str
    anchor_date: str
    include_in_report: bool
    interest: Money
    has_override: bool


@dataclass(frozen=True)
class YearSnapshot:
    """Everything the pure rules read for one (property, tax year)."""

    property_id: str
    tax_year: int
    report: ScheduleEReport
    prior_report: ScheduleEReport
    transactions: tuple[Transaction, ...]
    repairs: CategoryRows
    assets_with_rows: int
    loans: tuple[LoanFact, ...]
    carryforward: ReconciledYear | None
    status_tolerance: Money
    receipt_present: Mapping[str, bool]  # transaction id -> has a receipt


@dataclass(frozen=True)
class SwingChange:
    """A line's change from the prior year that reached the swing thresholds."""

    prior: Money
    current: Money
    change: Money  # signed: current - prior
    percent: Decimal | None  # one decimal; None when the prior total is 0.00


# ---------------------------------------------------------------------------
# Threshold helpers
# ---------------------------------------------------------------------------


def is_large_entry(amount: Decimal, config: ChecklistConfig) -> bool:
    """True when ``amount`` reaches the Large_Entry_Amount (inclusive)."""
    return amount >= config.large_entry_amount


def is_capital_candidate(amount: Decimal, config: ChecklistConfig) -> bool:
    """True when ``amount`` reaches the Capital_Candidate_Amount (inclusive)."""
    return amount >= config.capital_candidate_amount


def receipt_candidates(
    transactions: Iterable[Transaction], config: ChecklistConfig
) -> list[Transaction]:
    """Expense rows that are not imported and reach the Large_Entry_Amount."""
    return [
        t
        for t in transactions
        if t.type == "expense"
        and not t.imported
        and is_large_entry(t.amount, config)
    ]


def swing_for(
    prior: Money, current: Money, config: ChecklistConfig
) -> SwingChange | None:
    """Return the change when it is a swing, else ``None``.

    A swing needs ``abs(change) >= Swing_Minimum_Amount`` and either a zero
    prior total or a percentage (quantized to one decimal, half-up) at or above
    the Swing_Percent. The comparison uses the quantized percentage.
    """
    change = current - prior
    magnitude = abs(change)
    if magnitude < config.swing_minimum_amount:
        return None
    if prior == _ZERO:
        return SwingChange(prior, current, change, None)
    percent = (magnitude * _HUNDRED / abs(prior)).quantize(
        _ONE_TENTH, rounding=ROUND_HALF_UP
    )
    if percent >= config.swing_percent:
        return SwingChange(prior, current, change, percent)
    return None


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def _subtract_months(day: date, months: int) -> date:
    index = day.year * 12 + (day.month - 1) - months
    year, month = divmod(index, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def anchor_is_recent(anchor_date: str, tax_year: int, config: ChecklistConfig) -> bool:
    """True when the anchor is in the closed window ending December 31.

    The window runs from ``anchor_max_age_months`` before December 31 of
    ``tax_year`` (day clamped to the month length) through that December 31.
    An unparseable date is not recent.
    """
    try:
        anchor = date.fromisoformat(anchor_date)
    except (TypeError, ValueError):
        return False
    end = date(tax_year, 12, 31)
    start = _subtract_months(end, config.anchor_max_age_months)
    return start <= anchor <= end


def applicable_loan_count(loans: Iterable[LoanFact], tax_year: int) -> int:
    """Loans included in the report and anchored on or before December 31."""
    cutoff = f"{tax_year:04d}-12-31"
    return sum(1 for loan in loans if loan.include_in_report and loan.anchor_date <= cutoff)


def recent_years(data_years: Iterable[int], count: int) -> list[int]:
    """The ``count`` most recent distinct years, newest first."""
    return sorted(set(data_years), reverse=True)[:count]


def is_edited(transaction: Transaction) -> bool:
    """True when both timestamps parse and ``updated_at > created_at``."""
    if not transaction.created_at or not transaction.updated_at:
        return False
    try:
        created = datetime.fromisoformat(transaction.created_at)
        updated = datetime.fromisoformat(transaction.updated_at)
        return updated > created
    except (TypeError, ValueError):
        # Unparseable, or a naive and an aware timestamp that cannot compare.
        return False


# ---------------------------------------------------------------------------
# Counts, formatting, links
# ---------------------------------------------------------------------------


def build_counts(items: Iterable[ChecklistItem]) -> ChecklistCounts:
    done = needs = na = 0
    for item in items:
        if item.status == "done":
            done += 1
        elif item.status == "needs_attention":
            needs += 1
        else:
            na += 1
    return ChecklistCounts(done, needs, na, done + needs + na)


def format_money(amount: Decimal) -> str:
    """``$1,250.00`` (two decimals); a negative amount is ``-$1,250.00``."""
    quantized = amount.quantize(_CENTS, rounding=ROUND_HALF_UP)
    sign = "-" if quantized < _ZERO else ""
    return f"{sign}${abs(quantized):,.2f}"


def format_percent(value: Decimal) -> str:
    """A percentage without trailing zeros (``50``, ``62.5``)."""
    text = format(value.normalize(), "f")
    return text


def property_link(property_id: str, segment: str, year: int | None = None) -> str:
    """``/properties/{id}/{segment}``, with ``?year=`` for year-aware pages."""
    base = f"/properties/{property_id}/{segment}"
    if year is not None and segment in _YEAR_SEGMENTS:
        return f"{base}?year={year}"
    return base


def carryforward_link() -> str:
    return "/carryforward"


# ---------------------------------------------------------------------------
# Rules 1 to 5
# ---------------------------------------------------------------------------

_DEPRECIATION_LINE = 18


def _item(
    item_id: ItemId,
    title: str,
    status: Status,
    reason: str,
    link: str,
    details: dict[str, Any] | None = None,
) -> ChecklistItem:
    return ChecklistItem(item_id, title, status, reason, link, details)


def _rule_income_entered(snapshot: YearSnapshot, config: ChecklistConfig) -> ChecklistItem:
    year = snapshot.tax_year
    total = sum(
        (row.total for row in snapshot.report.lines if row.kind == "income"), _ZERO
    )
    total = to_money(total)
    link = property_link(snapshot.property_id, "transactions", year)
    if total > _ZERO:
        status: Status = "done"
        reason = f"Income of {format_money(total)} is entered for {year}."
    else:
        status = "needs_attention"
        reason = f"No income is entered for {year}."
    return _item(
        "income_entered", "Income entered", status, reason, link, {"income_total": total}
    )


def _rule_expenses_entered(snapshot: YearSnapshot, config: ChecklistConfig) -> ChecklistItem:
    year = snapshot.tax_year
    total = to_money(
        sum(
            (
                row.total
                for row in snapshot.report.lines
                if row.kind == "expense" and row.line != _DEPRECIATION_LINE
            ),
            _ZERO,
        )
    )
    link = property_link(snapshot.property_id, "transactions", year)
    if total > _ZERO:
        status: Status = "done"
        reason = (
            f"Expenses of {format_money(total)} are entered for {year}, "
            "not counting depreciation."
        )
    else:
        status = "needs_attention"
        reason = f"No expenses are entered for {year}, not counting depreciation."
    return _item(
        "expenses_entered",
        "Expenses entered",
        status,
        reason,
        link,
        {"expense_total": total},
    )


def _rule_depreciation_present(
    snapshot: YearSnapshot, config: ChecklistConfig
) -> ChecklistItem:
    year = snapshot.tax_year
    line = snapshot.report.line(_DEPRECIATION_LINE)
    line_total = to_money(line.total if line is not None else _ZERO)
    count = snapshot.assets_with_rows
    link = property_link(snapshot.property_id, "assets")
    if count == 0:
        status: Status = "not_applicable"
        reason = f"No asset has depreciation scheduled for {year}."
    elif line_total > _ZERO:
        status = "done"
        reason = (
            f"Depreciation of {format_money(line_total)} is on Line 18 "
            f"from {count} asset(s) scheduled for {year}."
        )
    else:
        status = "needs_attention"
        reason = (
            f"{count} asset(s) have depreciation scheduled for {year} "
            "but Line 18 is $0.00."
        )
    return _item(
        "depreciation_present",
        "Depreciation reflected",
        status,
        reason,
        link,
        {"assets_with_schedule_rows": count, "line_18_total": line_total},
    )


def _rule_line12_source(snapshot: YearSnapshot, config: ChecklistConfig) -> ChecklistItem:
    year = snapshot.tax_year
    detail = snapshot.report.line12
    source = detail.source
    superseded = detail.superseded_manual_interest
    line = snapshot.report.line(12)
    line_total = to_money(line.total if line is not None else _ZERO)
    applicable = applicable_loan_count(snapshot.loans, year)
    loan_generated = source == "loan-generated"
    if loan_generated or applicable > 0:
        link = property_link(snapshot.property_id, "loans")
    else:
        link = property_link(snapshot.property_id, "transactions", year)

    if loan_generated:
        if superseded.count == 0:
            status: Status = "done"
            reason = "Line 12 comes from the loan schedule."
        else:
            status = "needs_attention"
            reason = (
                f"Line 12 comes from the loan schedule. {superseded.count} manually "
                f"entered interest transaction(s) totaling "
                f"{format_money(superseded.amount)} are not used by the report."
            )
    elif line_total > _ZERO:
        status = "done"
        reason = "Line 12 comes from entered transactions."
    elif applicable == 0:
        status = "not_applicable"
        reason = f"No mortgage interest is entered for {year} and no loan applies."
    else:
        status = "needs_attention"
        reason = (
            f"A loan applies to {year} but produced no Line 12 interest, "
            "and none is entered."
        )
    return _item(
        "line12_source",
        "Mortgage interest source",
        status,
        reason,
        link,
        {
            "source": source,
            "line_12_total": line_total,
            "superseded_count": superseded.count,
            "superseded_amount": to_money(superseded.amount),
        },
    )


def _rule_loan_interest_confirmed(
    snapshot: YearSnapshot, config: ChecklistConfig
) -> ChecklistItem:
    year = snapshot.tax_year
    link = property_link(snapshot.property_id, "loans")
    title = "Loan interest confirmed"
    if snapshot.report.line12.source != "loan-generated":
        return _item(
            "loan_interest_confirmed",
            title,
            "not_applicable",
            f"Line 12 for {year} does not come from the loan schedule.",
            link,
        )
    rows: list[dict[str, Any]] = []
    unconfirmed = 0
    for loan in snapshot.loans:
        if not loan.include_in_report or loan.interest <= _ZERO:
            continue
        confirmed = loan.has_override or anchor_is_recent(
            loan.anchor_date, year, config
        )
        if not confirmed:
            unconfirmed += 1
        rows.append(
            {
                "loan_id": loan.loan_id,
                "name": loan.description,
                "confirmed": confirmed,
                "anchor_date": loan.anchor_date,
                "interest": to_money(loan.interest),
            }
        )
    if unconfirmed == 0:
        status: Status = "done"
        reason = (
            f"Loan interest for {year} is confirmed by an override or a recent "
            "balance checkpoint."
        )
    else:
        status = "needs_attention"
        reason = (
            f"{unconfirmed} loan(s) have no confirmed interest or balance checkpoint "
            f"within {config.anchor_max_age_months} month(s) of year end, so their "
            "interest is estimated from the schedule."
        )
    return _item(
        "loan_interest_confirmed", title, status, reason, link, {"loans": rows}
    )


# ---------------------------------------------------------------------------
# Rules 6 to 8
# ---------------------------------------------------------------------------

_CARRYFORWARD_PORTFOLIO_NOTE = (
    "This item covers all properties and is the same on every property's checklist."
)


def _rule_carryforward_reconciled(
    snapshot: YearSnapshot, config: ChecklistConfig
) -> ChecklistItem:
    year = snapshot.tax_year
    row = snapshot.carryforward
    tolerance = to_money(snapshot.status_tolerance)
    title = "Carryforward reconciled"
    link = carryforward_link()
    tail = (
        f"{_CARRYFORWARD_PORTFOLIO_NOTE} Status tolerance: {format_money(tolerance)}."
    )
    details: dict[str, Any] = {
        "status": row.status if row is not None else None,
        "reported_carry_in": row.reported_carryforward if row is not None else None,
        "expected_carry_in": row.expected_carry_in if row is not None else None,
        "drift": row.drift if row is not None else None,
        "carried_from_year": row.carried_from_year if row is not None else None,
        "status_tolerance": tolerance,
    }
    if row is None:
        return _item(
            "carryforward_reconciled",
            title,
            "not_applicable",
            f"The carryforward reconciliation has no row for {year}. {tail}",
            link,
            details,
        )
    expected = row.expected_carry_in
    if row.status == "ok":
        status: Status = "done"
        reason = f"The reported carry-in for {year} matches the expected carry-in. {tail}"
    elif row.status == "unreported":
        if expected > _ZERO:
            status = "needs_attention"
            reason = (
                f"No carry-in is reported for {year}; the expected carry-in is "
                f"{format_money(expected)}. {tail}"
            )
        else:
            status = "not_applicable"
            reason = f"No carry-in is expected for {year}. {tail}"
    elif row.status == "mismatch":
        status = "needs_attention"
        reported = row.reported_carryforward
        drift = row.drift
        reason = (
            f"The reported carry-in for {year} is "
            f"{format_money(reported) if reported is not None else 'not reported'}, "
            f"the expected carry-in is {format_money(expected)}, and the drift is "
            f"{format_money(drift) if drift is not None else 'unknown'}. {tail}"
        )
    else:  # carried
        status = "needs_attention"
        origin = (
            str(row.carried_from_year)
            if row.carried_from_year is not None
            else "an earlier year"
        )
        reason = (
            f"The carry-in for {year} differs from the expected carry-in because of "
            f"a difference carried from {origin}. {tail}"
        )
    return _item("carryforward_reconciled", title, status, reason, link, details)


def _rule_repairs_exceed_total(
    snapshot: YearSnapshot, config: ChecklistConfig
) -> ChecklistItem:
    year = snapshot.tax_year
    res = snapshot.repairs.resolution
    link = property_link(snapshot.property_id, "repairs", year)
    title = "Itemized repairs within the entered total"
    details: dict[str, Any] = {
        "entered_total": res.entered_total,
        "itemized_sum": res.itemized_sum,
        "remainder": res.remainder,
        "line_source": res.source,
    }
    if res.entered_total is None or res.itemized_count == 0:
        status: Status = "not_applicable"
        reason = (
            f"Repairs for {year} have no entered total or no itemized entries "
            "to compare."
        )
    elif res.remainder is not None and res.remainder < _ZERO:
        status = "needs_attention"
        reason = (
            f"Itemized repairs of {format_money(res.itemized_sum)} exceed the "
            f"entered total of {format_money(res.entered_total)} by "
            f"{format_money(-res.remainder)}."
        )
    else:
        status = "done"
        reason = (
            f"Itemized repairs of {format_money(res.itemized_sum)} are within the "
            f"entered total of {format_money(res.entered_total)}."
        )
    return _item("repairs_exceed_total", title, status, reason, link, details)


def _rule_repairs_capital_candidates(
    snapshot: YearSnapshot, config: ChecklistConfig
) -> ChecklistItem:
    year = snapshot.tax_year
    entries = snapshot.repairs.entries
    link = property_link(snapshot.property_id, "assets")
    repairs_link = property_link(snapshot.property_id, "repairs", year)
    title = "Large repairs to review"
    flagged = [e for e in entries if is_capital_candidate(e.amount, config)]
    details: dict[str, Any] = {
        "flagged_count": len(flagged),
        "entries": [
            {
                "id": e.id,
                "date": e.date,
                "description": e.description,
                "amount": to_money(e.amount),
                "link": repairs_link,
            }
            for e in flagged
        ],
    }
    threshold = format_money(config.capital_candidate_amount)
    if not entries:
        status: Status = "not_applicable"
        reason = f"There are no itemized repairs entries for {year}."
    elif flagged:
        status = "needs_attention"
        reason = (
            f"{len(flagged)} itemized repairs entr{'y is' if len(flagged) == 1 else 'ies are'} "
            f"at or above {threshold}. Review them: you decide whether each is a "
            "repair or an improvement."
        )
    else:
        status = "done"
        reason = f"No itemized repairs entry for {year} is at or above {threshold}."
    return _item("repairs_capital_candidates", title, status, reason, link, details)


# ---------------------------------------------------------------------------
# Rules 9 to 11 and the builder
# ---------------------------------------------------------------------------


def _rule_receipts_missing(snapshot: YearSnapshot, config: ChecklistConfig) -> ChecklistItem:
    year = snapshot.tax_year
    link = property_link(snapshot.property_id, "transactions", year)
    title = "Receipts on large expenses"
    candidates = receipt_candidates(snapshot.transactions, config)
    missing = [t for t in candidates if not snapshot.receipt_present.get(t.id, False)]
    threshold = format_money(config.large_entry_amount)
    details: dict[str, Any] = {
        "evaluated_count": len(candidates),
        "missing_count": len(missing),
        "transactions": [
            {
                "id": t.id,
                "date": t.date,
                "category": t.category_id,
                "description": t.description,
                "amount": to_money(t.amount),
            }
            for t in missing[:MAX_RECEIPT_DETAILS]
        ],
    }
    if not candidates:
        status: Status = "not_applicable"
        reason = (
            f"No entered expense for {year} is at or above {threshold}, so no "
            "receipts are checked."
        )
    elif missing:
        status = "needs_attention"
        reason = (
            f"{len(missing)} of {len(candidates)} expense(s) at or above "
            f"{threshold} have no receipt attached."
        )
    else:
        status = "done"
        reason = (
            f"All {len(candidates)} expense(s) at or above {threshold} have a "
            "receipt attached."
        )
    return _item("receipts_missing", title, status, reason, link, details)


def _rule_yoy_swings(snapshot: YearSnapshot, config: ChecklistConfig) -> ChecklistItem:
    year = snapshot.tax_year
    link = property_link(snapshot.property_id, "reports", year)
    title = "Year-over-year changes"
    prior_totals = {row.line: row.total for row in snapshot.prior_report.lines}
    if all(total == _ZERO for total in prior_totals.values()):
        return _item(
            "yoy_swings",
            title,
            "not_applicable",
            f"There is no prior-year data to compare with {year}.",
            link,
            {"swings": []},
        )
    swings: list[dict[str, Any]] = []
    for row in snapshot.report.lines:
        prior = prior_totals.get(row.line, _ZERO)
        found = swing_for(prior, row.total, config)
        if found is None:
            continue
        swings.append(
            {
                "line": row.line,
                "label": row.label,
                "prior_total": to_money(found.prior),
                "current_total": to_money(found.current),
                "change": to_money(found.change),
                "percent": found.percent,
            }
        )
    if not swings:
        status: Status = "done"
        reason = f"No line changed from the prior year by a review-worthy amount in {year}."
    else:
        status = "needs_attention"
        reason = (
            f"{len(swings)} line(s) changed by at least "
            f"{format_percent(config.swing_percent)}% and "
            f"{format_money(config.swing_minimum_amount)} from the prior year. "
            "Review these changes for a typing error or a missing entry."
        )
    return _item("yoy_swings", title, status, reason, link, {"swings": swings})


def _rule_imported_values_edited(
    snapshot: YearSnapshot, config: ChecklistConfig
) -> ChecklistItem:
    year = snapshot.tax_year
    link = property_link(snapshot.property_id, "transactions", year)
    title = "Imported values unchanged"
    imported = [t for t in snapshot.transactions if t.imported]
    edited = [t for t in imported if is_edited(t)]
    note = "Re-importing a Schedule E for this year replaces imported values."
    details: dict[str, Any] = {
        "imported_count": len(imported),
        "edited": [
            {
                "id": t.id,
                "schedule_e_line": t.schedule_e_line,
                "amount": to_money(t.amount),
                "updated_at": t.updated_at,
            }
            for t in edited
        ],
    }
    if not imported:
        status: Status = "not_applicable"
        reason = f"No values imported from a Schedule E exist for {year}. {note}"
    elif edited:
        status = "needs_attention"
        reason = (
            f"{len(edited)} imported line(s) were edited after import and may no "
            f"longer match the imported return. {note}"
        )
    else:
        status = "done"
        reason = f"All {len(imported)} imported line(s) are unchanged since import. {note}"
    return _item("imported_values_edited", title, status, reason, link, details)


_RULES = {
    "income_entered": _rule_income_entered,
    "expenses_entered": _rule_expenses_entered,
    "depreciation_present": _rule_depreciation_present,
    "line12_source": _rule_line12_source,
    "loan_interest_confirmed": _rule_loan_interest_confirmed,
    "carryforward_reconciled": _rule_carryforward_reconciled,
    "repairs_exceed_total": _rule_repairs_exceed_total,
    "repairs_capital_candidates": _rule_repairs_capital_candidates,
    "receipts_missing": _rule_receipts_missing,
    "yoy_swings": _rule_yoy_swings,
    "imported_values_edited": _rule_imported_values_edited,
}


def build_checklist(snapshot: YearSnapshot, config: ChecklistConfig) -> Checklist:
    """Run the eleven rules in ``ITEM_IDS`` order and assemble the Checklist."""
    items = tuple(_RULES[item_id](snapshot, config) for item_id in ITEM_IDS)
    return Checklist(
        property_id=snapshot.property_id,
        tax_year=snapshot.tax_year,
        items=items,
        counts=build_counts(items),
        thresholds=config.applied(),
    )


# ---------------------------------------------------------------------------
# Gatherer: read-only snapshot builder over the existing services
# ---------------------------------------------------------------------------


class _RequestCache:
    """Per-request memo: one reconciliation and one report per (property, year)."""

    def __init__(
        self, reports: ReportingService, carryforward: CarryforwardService
    ) -> None:
        self._reports = reports
        self._carryforward = carryforward
        self._reconciliation: ReconciliationSummary | None = None
        self._report_results: dict[tuple[str, int], Result[ScheduleEReport]] = {}

    def report(self, property_id: str, year: int) -> Result[ScheduleEReport]:
        key = (property_id, year)
        if key not in self._report_results:
            self._report_results[key] = self._reports.report_for(property_id, year)
        return self._report_results[key]

    def reconcile(self) -> ReconciliationSummary:
        if self._reconciliation is None:
            self._reconciliation = self._carryforward.reconcile()
        return self._reconciliation


class ChecklistService:
    """Read-only gatherer: builds a ``YearSnapshot`` and runs the pure rules."""

    def __init__(
        self,
        reports: ReportingService,
        transactions: TransactionService,
        depreciation: DepreciationService,
        loans: LoanService,
        properties: PropertyService,
        carryforward: CarryforwardService,
        config: ChecklistConfig = CHECKLIST_CONFIG,
    ) -> None:
        self._reports = reports
        self._transactions = transactions
        self._depreciation = depreciation
        self._loans = loans
        self._properties = properties
        self._carryforward = carryforward
        self._config = config

    # --- public API ---------------------------------------------------------

    def checklist_for(
        self, property_id: str, tax_year: int | None
    ) -> Result[Checklist]:
        year = latest_tax_year() if tax_year is None else tax_year
        cache = _RequestCache(self._reports, self._carryforward)
        return self._build(property_id, year, cache)

    def property_summary(
        self, property_id: str
    ) -> Result[PropertyChecklistSummary]:
        prop = self._properties.get(property_id)
        if not prop.is_ok:
            return Result.failure(
                prop.error.kind, prop.error.message, prop.error.field
            )
        cache = _RequestCache(self._reports, self._carryforward)
        years = recent_years(
            derive_data_years(
                [prop.value],
                self._transactions,
                self._depreciation,
                self._loans,
            ),
            self._config.summary_year_count,
        )
        summaries: list[ChecklistSummary] = []
        for year in years:
            built = self._build(property_id, year, cache)
            if not built.is_ok:
                return Result.failure(
                    built.error.kind, built.error.message, built.error.field
                )
            summaries.append(ChecklistSummary(year, built.value.counts))
        return Result.success(
            PropertyChecklistSummary(property_id, tuple(summaries))
        )

    def portfolio_summary(
        self, tax_year: int | None
    ) -> Result[PortfolioChecklistSummary]:
        year = latest_tax_year() if tax_year is None else tax_year
        cache = _RequestCache(self._reports, self._carryforward)
        rows: list[PropertyChecklistRow] = []
        for prop in self._properties.list():
            built = self._build(prop.id, year, cache)
            if not built.is_ok:
                return Result.failure(
                    built.error.kind, built.error.message, built.error.field
                )
            rows.append(
                PropertyChecklistRow(prop.id, prop.name, built.value.counts)
            )
        return Result.success(PortfolioChecklistSummary(year, tuple(rows)))

    # --- snapshot gathering -------------------------------------------------

    def _build(
        self, property_id: str, year: int, cache: _RequestCache
    ) -> Result[Checklist]:
        snapshot = self._gather(property_id, year, cache)
        if not snapshot.is_ok:
            return Result.failure(
                snapshot.error.kind, snapshot.error.message, snapshot.error.field
            )
        return Result.success(build_checklist(snapshot.value, self._config))

    def _gather(
        self, property_id: str, year: int, cache: _RequestCache
    ) -> Result[YearSnapshot]:
        report = cache.report(property_id, year)
        if not report.is_ok:
            return Result.failure(
                report.error.kind, report.error.message, report.error.field
            )
        prior = cache.report(property_id, year - 1)
        if not prior.is_ok:
            return Result.failure(
                prior.error.kind, prior.error.message, prior.error.field
            )

        listed = self._transactions.list_for_property(property_id, year)
        if not listed.is_ok:
            return Result.failure(
                listed.error.kind, listed.error.message, listed.error.field
            )
        transactions = tuple(listed.value)
        repairs = resolve_category_rows(transactions, "repairs")

        receipt_present = {
            t.id: self._transactions.has_receipt(property_id, t)
            for t in receipt_candidates(transactions, self._config)
        }

        assets_with_rows = sum(
            1
            for asset in self._depreciation.list_assets(property_id)
            if any(
                row.tax_year == year
                for row in self._depreciation.schedule_for(property_id, asset.id)
            )
        )

        try:
            facts = self._loans.year_facts(property_id, year)
        except StoredLoanError as exc:
            return Result.failure(
                "conflict",
                f"Stored loan has an invalid {exc.field} value.",
                exc.field,
            )
        loans = tuple(
            LoanFact(
                loan_id=f.loan_id,
                description=f.description,
                anchor_date=f.anchor_date,
                include_in_report=f.include_in_report,
                interest=f.interest,
                has_override=f.has_override,
            )
            for f in facts
        )

        reconciliation = cache.reconcile()
        carryforward = next(
            (r for r in reconciliation.years if r.tax_year == year), None
        )

        return Result.success(
            YearSnapshot(
                property_id=property_id,
                tax_year=year,
                report=report.value,
                prior_report=prior.value,
                transactions=transactions,
                repairs=repairs,
                assets_with_rows=assets_with_rows,
                loans=loans,
                carryforward=carryforward,
                status_tolerance=reconciliation.status_tolerance,
                receipt_present=receipt_present,
            )
        )


class ChecklistProvider(Protocol):
    """Read-only source of a year-end checklist, used by the accountant package."""

    def checklist_for(self, property_id: str, tax_year: int) -> Result[Checklist]: ...


def provider_for(wiring: Any, user: UserContext | str) -> ChecklistProvider:
    """Return a read-only provider for ``user``. Raises when a collaborator cannot be built."""
    # Lazy import: the router imports this module, so a top-level import would cycle.
    from logstead.router.handler import build_checklist_service

    return build_checklist_service(wiring, user)
