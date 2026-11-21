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
    from logstead.services.depreciation import DepreciationService
    from logstead.services.loan import LoanService
    from logstead.services.property import PropertyService
    from logstead.services.report import ReportingService
    from logstead.services.transaction import TransactionService


__all__ = [
    "ADD_FIRST_PROPERTY_PROMPT",
    "PropertySummary",
    "DashboardSummary",
    "PropertyAssetSummary",
    "AssetSummary",
    "PropertyYearPoint",
    "TrendYear",
    "TrendsSummary",
    "DashboardService",
    "derive_data_years",
    "earliest_data_year",
    "latest_tax_year",
]


#: The empty-state prompt shown when the user owns no properties (Requirement 11.4).
ADD_FIRST_PROPERTY_PROMPT: str = "Add your first property to get started."


def _current_tax_year() -> int:
    """The current calendar year (the raw "now" year)."""
    return datetime.now(timezone.utc).year


def latest_tax_year() -> int:
    """The latest *completed* tax year, i.e. the prior calendar year.

    A tax year can only be filed once it is over, so the current calendar year
    is never a meaningful Tax_Year for the dashboard, per-property summaries, the
    year-over-year trends, or the carryforward reconciliation. The latest
    selectable/derivable year is therefore the current calendar year minus one.

    This is the shared cap used by both :class:`DashboardService` and the
    carryforward service, so both derive the identical Data_Year span.
    """
    return _current_tax_year() - 1


#: Backwards-compatible alias for the module-private cap name that existing
#: dashboard tests import. :func:`latest_tax_year` is the public spelling shared
#: with the carryforward service.
_latest_tax_year = latest_tax_year


def derive_data_years(
    properties: list,
    transactions: "TransactionService | None",
    depreciation: "DepreciationService",
    loans: "LoanService | None" = None,
) -> list[int]:
    """Ascending list of a user's Data_Years across the given properties (Req 2).

    A *Data_Year* is a tax year for which the user has any Schedule E data,
    unioned across every owned property. A property contributes a year when
    either (a) it has one or more transactions in that year — the
    income/expense half of Schedule E — or (b) it has one or more depreciation
    schedule rows in that year, which feed Line 18.

    The derivation makes one pass per property, reusing the existing query
    paths: :meth:`TransactionService.list_for_property` for transaction years
    (``int(txn.date[:4])``) and :meth:`DepreciationService.list_assets` +
    :meth:`DepreciationService.schedule_for` for depreciation years
    (``row.tax_year``). No persisted data is read beyond those existing items
    and nothing is mutated.

    The result is sorted ascending and de-duplicated (each Data_Year appears
    once; Req 2.2, 2.3). Non-contiguous years are preserved exactly — no gap
    year is inserted (Req 2.4). The only ceiling is the latest *completed* tax
    year (:func:`latest_tax_year`): the current calendar year can't be filed
    yet, and a depreciation schedule materializes rows for every year of an
    asset's recovery period (decades into the future), so both are excluded
    (Req 2.5). When ``properties`` is empty the loop never runs and the result
    is empty (Req 11.4).

    This is the single shared implementation reused by both the dashboard
    (:meth:`DashboardService._derive_data_years`) and the carryforward service,
    so the two never diverge.

    Args:
        properties: The user's properties (already listed by the caller).
        transactions: The transaction service used to collect transaction tax
            years; ``None`` skips the transaction half (the numeric-summary
            callers do not wire it).
        depreciation: The depreciation service used to collect schedule years.
        loans: Optional loan service; when given, each property's
            :meth:`LoanService.report_years` (years with a rollup from an
            included loan) are unioned in. ``None`` leaves behavior unchanged.

    Returns:
        The ascending, de-duplicated list of Data_Years (Req 2.1).
    """
    data_years: set[int] = set()
    for prop in properties:
        # (a) Transaction tax years: list every transaction (all years) and
        # take the four-digit year prefix of its ISO date.
        if transactions is not None:
            result = transactions.list_for_property(prop.id)
            if result.is_ok:
                for txn in result.value:
                    data_years.add(int(txn.date[:4]))
        # (b) Depreciation schedule years: every materialized schedule row's
        # tax year across the property's assets (these feed Line 18).
        for asset in depreciation.list_assets(prop.id):
            for row in depreciation.schedule_for(prop.id, asset.id):
                data_years.add(row.tax_year)
        # (c) Loan years: years with a rollup from an included loan.
        if loans is not None:
            data_years |= set(loans.report_years(prop.id))
    # A tax year is only meaningful once it is over, and depreciation
    # schedules materialize a row for every year of an asset's recovery
    # period (which runs well into the future). Cap the Data_Years at
    # the latest completed tax year so the series never surfaces a
    # not-yet-filable or future depreciation-only year (Req 2.5).
    latest = latest_tax_year()
    return sorted(year for year in data_years if year <= latest)


def earliest_data_year(
    property_id: str,
    transactions: "TransactionService",
    depreciation: "DepreciationService",
    loans: "LoanService | None" = None,
) -> int | None:
    """Earliest calendar year with any activity for one property.

    The smaller of (a) the year of the property's earliest transaction, read
    cheaply via :meth:`TransactionService.earliest_year` (one item, not a full
    load), and (b) the year of its earliest depreciable asset's
    placed-in-service date from :meth:`DepreciationService.list_assets`. A
    depreciation schedule starts in the in-service year, so assets alone cover
    the depreciation side. Read-only; nothing is mutated and no cap is applied
    (a year later than the latest completed tax year is returned as-is).

    Args:
        property_id: The (already ownership-checked) property identifier.
        transactions: The transaction service.
        depreciation: The depreciation service.

    Returns:
        The earliest activity year, or ``None`` when the property has neither
        transactions nor assets.
    """
    candidates: list[int] = []
    txn_year = transactions.earliest_year(property_id)
    if txn_year is not None:
        candidates.append(txn_year)
    for asset in depreciation.list_assets(property_id):
        candidates.append(int(asset.placed_in_service_date[:4]))
    if loans is not None:
        loan_year = loans.earliest_year(property_id)
        if loan_year is not None:
            candidates.append(loan_year)
    return min(candidates) if candidates else None


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
class PropertyYearPoint:
    """One property's income / expense / net for a single Data_Year (Req 6.2, 11.2).

    The trends analogue of :class:`PropertySummary`: it carries the same three
    figures for one property in one year of the year-over-year series. Every
    monetary figure is a two-decimal ``Decimal`` taken from that property's
    Schedule E report totals for the year, so a trend point stays consistent
    with the report (design Property 1). A property with no data in a Data_Year
    still appears, contributing ``0.00`` with ``net == 0.00``.

    Attributes:
        property_id: The property identifier.
        property_name: The property's display name.
        total_income: Total income for the property in the year.
        total_expenses: Total expenses for the property in the year (includes
            depreciation, matching the Schedule E report).
        net: ``total_income - total_expenses`` (negative denotes a loss).
    """

    property_id: str
    property_name: str
    total_income: Money
    total_expenses: Money
    net: Money


@dataclass(frozen=True)
class TrendYear:
    """The portfolio figures for one Data_Year in the trends series (Req 6.2, 7.1).

    One year of the year-over-year series: the portfolio totals (sum of the
    per-property report totals), the portfolio depreciation total (sum of the
    per-property Schedule E Line 18 figures), and the per-property breakdown for
    that year. The portfolio ``net`` equals the exact-cent sum of the
    per-property nets.

    Attributes:
        tax_year: The four-digit Data_Year every figure is derived for.
        total_income: Portfolio total income (sum of per-property income).
        total_expenses: Portfolio total expenses (sum of per-property expenses).
        net: Portfolio net = exact-cent sum of the per-property nets.
        properties: Per-property points for the year, in the order the property
            service lists them; every owned property appears.
        depreciation_total: Portfolio depreciation total for the year (exact-cent
            sum of the per-property Line 18 figures), a two-decimal ``Decimal``.
    """

    tax_year: int
    total_income: Money
    total_expenses: Money
    net: Money
    properties: tuple[PropertyYearPoint, ...]
    depreciation_total: Money


@dataclass(frozen=True)
class TrendsSummary:
    """The year-over-year trends series for a user (Requirements 6.2, 7.1, 11.2).

    Carries one :class:`TrendYear` per Data_Year, ascending with no gaps and no
    cap. An empty portfolio (or one with no data years) yields an empty
    ``years`` tuple.

    Attributes:
        years: The trend years, ascending by ``tax_year`` (empty when the user
            owns no properties or has no data years).
    """

    years: tuple[TrendYear, ...]


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


@dataclass(frozen=True)
class PropertyAssetSummary:
    """One property's depreciable-asset count and depreciation total (Req 3.1).

    The ``depreciation_total`` is the authoritative per-(property, year) figure
    produced by :meth:`DepreciationService.property_depreciation_for_year` — the
    same method that feeds Schedule E Line 18 — so the dashboard summary and
    Line 18 are the same number by construction (Requirement 6.1).

    Attributes:
        property_id: The property identifier.
        property_name: The property's display name.
        asset_count: Count of the property's :class:`DepreciableAsset` records.
        depreciation_total: The property's depreciation total for the tax year,
            a two-decimal ``Decimal`` (serialized as a string by the router).
    """

    property_id: str
    property_name: str
    asset_count: int
    depreciation_total: Money


@dataclass(frozen=True)
class AssetSummary:
    """Per-property depreciable-assets summary for a user + tax year (Req 3.1).

    Carries one :class:`PropertyAssetSummary` per property the user owns, in the
    order the property service lists them. An empty portfolio yields an empty
    ``properties`` tuple.

    Attributes:
        tax_year: The tax year every depreciation total is derived for.
        properties: Per-property asset summaries (empty when the user owns no
            properties).
    """

    tax_year: int
    properties: tuple[PropertyAssetSummary, ...]


class DashboardService:
    """Numeric portfolio / per-property dashboard summaries (Requirement 11).

    Args:
        properties: The property service, used to list the user's properties
            (and to detect the empty state).
        reports: The reporting service, used to derive each property's
            income / expense / net from its Schedule E report so the dashboard
            matches the report exactly.
        depreciation: The depreciation service, used by
            :meth:`asset_summary` for each property's asset count and its
            authoritative per-year depreciation total (the same figure that
            feeds Schedule E Line 18). Injected per request by the router's
            ``_dashboard_service_or_503`` constructor.
        transactions: The transaction service, used by
            :meth:`_derive_data_years` to collect each property's
            transaction tax years (the income/expense half of a Data_Year).
            Optional so existing callers that only use the numeric summaries
            keep working; the year-over-year trends path requires it.
        loans: Optional loan service; when given, loan report years count as
            Data_Years. ``None`` leaves behavior unchanged.
    """

    def __init__(
        self,
        properties: "PropertyService",
        reports: "ReportingService",
        depreciation: "DepreciationService",
        transactions: "TransactionService | None" = None,
        loans: "LoanService | None" = None,
    ) -> None:
        self._properties = properties
        self._reports = reports
        self._depreciation = depreciation
        self._transactions = transactions
        self._loans = loans

    # --- Empty state (Requirement 11.4) -------------------------------------

    def has_properties(self) -> bool:
        """True when the authenticated user owns at least one property (11.4)."""
        return len(self._properties.list()) > 0

    # --- Data_Year derivation (Requirement 2) -------------------------------

    def _derive_data_years(self, properties: list) -> list[int]:
        """Ascending list of the user's Data_Years across all properties (Req 2).

        Thin instance wrapper over the shared module-level
        :func:`derive_data_years`, binding this service's injected transaction
        and depreciation collaborators. The behavior is byte-for-byte identical
        to the previous inline implementation — the same union of transaction
        and depreciation-schedule years, ascending, de-duplicated,
        gap-preserving, capped at :func:`latest_tax_year`. Extracted so the
        carryforward service can reuse the exact same derivation without
        duplicating it.

        Args:
            properties: The user's properties (already listed by the caller, so
                the single ``PropertyService.list()`` is not repeated here).

        Returns:
            The ascending, de-duplicated list of Data_Years (Req 2.1).
        """
        return derive_data_years(
            properties, self._transactions, self._depreciation, self._loans
        )

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
        year = _latest_tax_year() if tax_year is None else tax_year
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
        year = _latest_tax_year() if tax_year is None else tax_year
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

    # --- Year-over-year trends (Requirements 2, 6, 11) ----------------------

    def trends_summary(self) -> TrendsSummary:
        """Portfolio-level, multi-year trends across every Data_Year (Req 2, 6, 11).

        Lists the authenticated user's properties once (user-scoped via the
        injected :class:`PropertyService`, Req 6.6) and returns an empty series
        immediately when the user owns none (Req 11.4). Otherwise derives the
        ascending Data_Years (Req 2) and, for each year, loops the properties
        making exactly one :meth:`ReportingService.report_for` and one
        :meth:`DepreciationService.property_depreciation_for_year` call per
        (property, Data_Year) pair (Req 11.1).

        Each per-property point's income / expense / net is taken straight from
        that property's Schedule E report totals, so the figures reconcile with
        the report to the cent (Req 6.3). A non-ok report contributes ``0.00``
        and still appears as a :class:`PropertyYearPoint` with ``net == 0.00``,
        mirroring the :meth:`per_property_summary` skip and never mutating
        persisted data (Req 6.7, 11.3). The portfolio
        ``total_income``/``total_expenses``/``net`` are the exact-cent sums of
        the per-property report totals (Req 6.5), and ``depreciation_total`` is
        the exact-cent sum of the per-property depreciation (Req 6.4); every
        figure is carried via :func:`to_money` (Req 6.2).
        """
        properties = self._properties.list()
        if not properties:
            return TrendsSummary(years=())

        years: list[TrendYear] = []
        for year in self._derive_data_years(properties):
            port_income = Decimal("0.00")
            port_expenses = Decimal("0.00")
            port_net = Decimal("0.00")
            port_depreciation = Decimal("0.00")
            points: list[PropertyYearPoint] = []
            for prop in properties:
                report = self._reports.report_for(prop.id, year)
                depreciation = self._depreciation.property_depreciation_for_year(
                    prop.id, year
                )
                port_depreciation += depreciation
                # report_for only fails for a missing/unowned property; every id
                # here came straight from the user's own property list. A non-ok
                # report contributes 0.00 but still appears (mirrors the
                # per_property_summary skip).
                if not report.is_ok:
                    zero = to_money(Decimal("0.00"))
                    points.append(
                        PropertyYearPoint(
                            property_id=prop.id,
                            property_name=prop.name,
                            total_income=zero,
                            total_expenses=zero,
                            net=zero,
                        )
                    )
                    continue
                totals = report.value.totals
                port_income += totals.total_income
                port_expenses += totals.total_expenses
                port_net += totals.net
                points.append(
                    PropertyYearPoint(
                        property_id=prop.id,
                        property_name=prop.name,
                        total_income=to_money(totals.total_income),
                        total_expenses=to_money(totals.total_expenses),
                        net=to_money(totals.net),
                    )
                )
            years.append(
                TrendYear(
                    tax_year=year,
                    total_income=to_money(port_income),
                    total_expenses=to_money(port_expenses),
                    net=to_money(port_net),
                    properties=tuple(points),
                    depreciation_total=to_money(port_depreciation),
                )
            )
        return TrendsSummary(years=tuple(years))

    # --- Depreciable-assets summary (Requirements 3.1, 3.3, 3.4, 6.1) -------

    def asset_summary(self, tax_year: int | None = None) -> AssetSummary:
        """Per-property depreciable-assets summary for a tax year (Req 3.1).

        Lists the authenticated user's properties (user-scoped, Requirement
        3.4) and, for each, reports its depreciable-asset count and its
        depreciation total for the year. The count comes from
        :meth:`DepreciationService.list_assets` and the total from
        :meth:`DepreciationService.property_depreciation_for_year` — the SAME
        authoritative figure that feeds Schedule E Line 18, so the dashboard and
        the return reconcile by construction (Requirement 6.1). No new data is
        read beyond the existing per-property asset/schedule items (Requirement
        3.3). Defaults to the current tax year when ``tax_year`` is omitted; an
        empty portfolio returns ``properties=()``.
        """
        year = _latest_tax_year() if tax_year is None else tax_year
        rows: list[PropertyAssetSummary] = []
        for prop in self._properties.list():
            assets = self._depreciation.list_assets(prop.id)
            total = self._depreciation.property_depreciation_for_year(prop.id, year)
            rows.append(
                PropertyAssetSummary(
                    property_id=prop.id,
                    property_name=prop.name,
                    asset_count=len(assets),
                    depreciation_total=to_money(total),
                )
            )
        return AssetSummary(tax_year=year, properties=tuple(rows))

    #: Convenience alias for :meth:`portfolio_summary` (the "summary" entry point).
    summary = portfolio_summary
