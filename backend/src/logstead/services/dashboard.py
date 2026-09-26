"""Dashboard Service: numeric portfolio and per-property summaries (Requirement 11).

The dashboard gives the LLC owner an at-a-glance financial overview for a tax
year: total income, total expenses, and net income or loss across all
properties (Requirement 11.1), plus a per-property breakdown of the same three
figures (Requirement 11.2). A different tax year can be requested to re-derive
every figure for that year (Requirement 11.3). When the user owns no
properties, the dashboard surfaces an "add your first property" prompt rather
than an error (Requirement 11.4).

Numbers only
------------
This release renders the dashboard as **numeric** income / expense / net
summaries — there is no chart or visualization data in the summary shape
(design "Dashboard Component"). Charts are a documented future direction and
add no behavior here.

Consistency with the Schedule E report
---------------------------------------
Rather than re-aggregating transactions itself, the dashboard **reuses the
Schedule E report** for each property via the injected
:class:`ReportingService`. Each per-property summary's income / expense / net is
taken directly from that property's :class:`ScheduleEReport` totals, so a
property's dashboard net is *always* identical to its report net, and the
portfolio net is the sum of the per-property nets (design Property 26). This is
the same aggregation the combined report performs, exposed in a dashboard-shaped
result.

Collaborators (the property and reporting services) are injected so the whole
service can be exercised against ``moto`` with no live AWS call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from logstead.util.money import Money, to_money

if TYPE_CHECKING:
    from logstead.services.property import PropertyService
    from logstead.services.report import ReportingService


__all__ = [
    "ADD_FIRST_PROPERTY_PROMPT",
    "PropertySummary",
    "DashboardSummary",
    "DashboardService",
]


#: The empty-state prompt shown when the user owns no properties (Requirement 11.4).
ADD_FIRST_PROPERTY_PROMPT: str = "Add your first property to get started."


def _current_tax_year() -> int:
    """The current calendar year, used as the dashboard's default tax year (11.3)."""
    return datetime.now(timezone.utc).year


@dataclass(frozen=True)
class PropertySummary:
    """One property's income / expense / net for a tax year (Requirement 11.2).

    Every monetary figure is a two-decimal ``Decimal`` and equals the
    corresponding total on that property's Schedule E report for the year, so
    the dashboard stays consistent with the report (design Property 26).

    Attributes:
        property_id: The property identifier.
        property_name: The property's display name.
        total_income: Total income for the year.
        total_expenses: Total expenses for the year (includes depreciation,
            matching the Schedule E report).
        net: ``total_income - total_expenses`` (negative denotes a loss).
    """

    property_id: str
    property_name: str
    total_income: Money
    total_expenses: Money
    net: Money


@dataclass(frozen=True)
class DashboardSummary:
    """The numeric dashboard summary for a user + tax year (Requirement 11).

    Carries the portfolio totals (Requirement 11.1), the per-property breakdown
    (Requirement 11.2), and the empty-state flag/prompt (Requirement 11.4). No
    chart or visualization data is included — numeric summaries only.

    Attributes:
        tax_year: The tax year every figure is derived for (Requirement 11.3).
        has_properties: ``False`` when the user owns no properties; when
            ``False`` the totals are zero, ``properties`` is empty, and
            ``empty_state_prompt`` carries the add-first-property guidance.
        total_income: Portfolio total income (sum of per-property income).
        total_expenses: Portfolio total expenses (sum of per-property expenses).
        net: Portfolio net = sum of the per-property nets (design Property 26).
        properties: Per-property summaries, in the order the property service
            lists them.
        empty_state_prompt: The add-first-property prompt when
            ``has_properties`` is ``False``; otherwise ``None``.
    """

    tax_year: int
    has_properties: bool
    total_income: Money
    total_expenses: Money
    net: Money
    properties: tuple[PropertySummary, ...]
    empty_state_prompt: str | None = None


class DashboardService:
    """Numeric portfolio / per-property dashboard summaries (Requirement 11).

    Args:
        properties: The property service, used to list the user's properties
            (and to detect the empty state).
        reports: The reporting service, used to derive each property's
            income / expense / net from its Schedule E report so the dashboard
            matches the report exactly.
    """

    def __init__(
        self,
        properties: "PropertyService",
        reports: "ReportingService",
    ) -> None:
        self._properties = properties
        self._reports = reports

    # --- Empty state (Requirement 11.4) -------------------------------------

    def has_properties(self) -> bool:
        """True when the authenticated user owns at least one property (11.4)."""
        return len(self._properties.list()) > 0

    # --- Summaries (Requirements 11.1-11.4) ---------------------------------

    def per_property_summary(
        self, tax_year: int | None = None
    ) -> list[PropertySummary]:
        """Per-property income / expense / net for a tax year (Requirement 11.2).

        Defaults to the current tax year when ``tax_year`` is omitted
        (Requirement 11.3). Each summary is taken from the property's Schedule E
        report totals so it matches the report. Returns an empty list when the
        user owns no properties.
        """
        year = _current_tax_year() if tax_year is None else tax_year
        summaries: list[PropertySummary] = []
        for prop in self._properties.list():
            report = self._reports.report_for(prop.id, year)
            # report_for only fails for a missing/unowned property; every id
            # here came straight from the user's own property list.
            if not report.is_ok:
                continue
            totals = report.value.totals
            summaries.append(
                PropertySummary(
                    property_id=prop.id,
                    property_name=prop.name,
                    total_income=to_money(totals.total_income),
                    total_expenses=to_money(totals.total_expenses),
                    net=to_money(totals.net),
                )
            )
        return summaries

    def portfolio_summary(self, tax_year: int | None = None) -> DashboardSummary:
        """The full numeric dashboard summary for a tax year (Requirement 11).

        Produces the portfolio totals (Requirement 11.1) and the per-property
        breakdown (Requirement 11.2) for the given year, defaulting to the
        current tax year (Requirement 11.3). The portfolio net equals the sum of
        the per-property nets (design Property 26). When the user owns no
        properties, returns an empty-state summary carrying
        :data:`ADD_FIRST_PROPERTY_PROMPT` with zeroed totals (Requirement 11.4).
        """
        year = _current_tax_year() if tax_year is None else tax_year
        per_property = self.per_property_summary(year)

        if not per_property:
            zero = to_money(Decimal("0.00"))
            return DashboardSummary(
                tax_year=year,
                has_properties=False,
                total_income=zero,
                total_expenses=zero,
                net=zero,
                properties=(),
                empty_state_prompt=ADD_FIRST_PROPERTY_PROMPT,
            )

        total_income = Decimal("0.00")
        total_expenses = Decimal("0.00")
        net = Decimal("0.00")
        for summary in per_property:
            total_income += summary.total_income
            total_expenses += summary.total_expenses
            net += summary.net

        return DashboardSummary(
            tax_year=year,
            has_properties=True,
            total_income=to_money(total_income),
            total_expenses=to_money(total_expenses),
            net=to_money(net),
            properties=tuple(per_property),
            empty_state_prompt=None,
        )

    #: Convenience alias for :meth:`portfolio_summary` (the "summary" entry point).
    summary = portfolio_summary
