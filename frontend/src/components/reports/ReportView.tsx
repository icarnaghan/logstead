import { lazy } from "react";
import {
  DEPRECIATION_LINE,
  OTHER_LINE,
  type ScheduleEReport,
} from "../../api/reports";
import { formatMoney } from "../../lib/money";
import { Card } from "../ui";
import { ScheduleELineTable } from "./ScheduleELineTable";
import { OtherItemsList } from "./OtherItemsList";
import { ChartCard } from "../charts/ChartCard";
import { LazyChart } from "../charts/LazyChart";
import { expenseByCategory } from "../charts/prepare";
import { ExpenseByCategoryTable } from "../charts/ExpenseByCategoryTable";

/**
 * The expense-by-category chart is the lazy boundary: Recharts is reached only
 * through this `React.lazy` import, so it code-splits into its own async chunk
 * absent from the initial paint (Requirement 14). The always-present data table
 * lives in a Recharts-free module and is imported eagerly above.
 */
const ExpenseByCategoryChart = lazy(
  () => import("../charts/ExpenseByCategoryChart"),
);

interface ReportViewProps {
  /** The fetched Schedule E report to render. */
  report: ScheduleEReport;
  /**
   * Prefix for the generated section-heading element ids. Defaults to a stable
   * value for the standalone per-property page; the combined report passes a
   * per-property prefix so multiple `ReportView`s can be composed on one page
   * without duplicate ids (which would break the `aria-labelledby` wiring and
   * fail accessibility checks).
   */
  idPrefix?: string;
  /**
   * Whether each report grouping is exposed as a named landmark `region`.
   * Defaults to `true` for the standalone per-property page. The combined
   * report composes many `ReportView`s, so it passes `false` to render the
   * groupings as `role="group"` (still labelled, but not landmarks) — this
   * keeps the page's landmark set uncluttered and uniquely distinguishable.
   */
  region?: boolean;
}

/** True when a two-decimal money string represents a negative amount (a loss). */
function isLoss(amount: string): boolean {
  return Number(amount) < 0;
}

/**
 * Renders a per-property Schedule E report (Requirement 10) as
 * numbers-and-forms — never a chart.
 *
 * It shows the report header (property name/address/type and the year's
 * fair-rental & personal-use days), the per-line Schedule E totals split into
 * income and expense tables, the Line 18 depreciation total, the itemized
 * Line 19 "Other" expenses, and the income / expense / net totals. A negative
 * net is presented as a loss.
 */
export function ReportView({
  report,
  idPrefix = "report",
  region = true,
}: ReportViewProps) {
  const { header, lines, other_items, totals } = report;

  // When not a landmark region, expose each grouping as a labelled group so the
  // heading association is preserved without adding a landmark.
  const sectionRole = region ? undefined : "group";

  const headerHeadingId = `${idPrefix}-header-heading`;
  const incomeHeadingId = `${idPrefix}-income-heading`;
  const expensesHeadingId = `${idPrefix}-expenses-heading`;
  const depreciationHeadingId = `${idPrefix}-depreciation-heading`;
  const otherHeadingId = `${idPrefix}-other-heading`;
  const totalsHeadingId = `${idPrefix}-totals-heading`;

  const incomeLines = lines.filter((line) => line.kind === "income");
  const expenseLines = lines.filter((line) => line.kind === "expense");
  // Ranked (desc) expense-by-category data for the chart (Req 16.1, 16.3).
  const expenseData = expenseByCategory(report);
  const depreciationLine = lines.find((line) => line.line === DEPRECIATION_LINE);
  const otherLine = lines.find((line) => line.line === OTHER_LINE);

  const netLoss = isLoss(totals.net);

  return (
    <div className="space-y-8">
      <Card
        as="section"
        role={sectionRole}
        aria-labelledby={headerHeadingId}
        className="break-inside-avoid p-4"
      >
        <h2
          id={headerHeadingId}
          className="text-lg font-semibold text-fg"
        >
          {header.property_name}
        </h2>
        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="font-medium text-fg-muted">Address</dt>
            <dd className="text-fg">{header.address || "—"}</dd>
          </div>
          <div>
            <dt className="font-medium text-fg-muted">Property type</dt>
            <dd className="text-fg">{header.property_type ?? "—"}</dd>
          </div>
          <div>
            <dt className="font-medium text-fg-muted">Tax year</dt>
            <dd className="tabular-nums text-fg">{header.tax_year}</dd>
          </div>
          <div>
            <dt className="font-medium text-fg-muted">Fair rental days</dt>
            <dd className="tabular-nums text-fg">
              {header.fair_rental_days}
            </dd>
          </div>
          <div>
            <dt className="font-medium text-fg-muted">Personal use days</dt>
            <dd className="tabular-nums text-fg">
              {header.personal_use_days}
            </dd>
          </div>
        </dl>
      </Card>

      <Card
        as="section"
        role={sectionRole}
        aria-labelledby={incomeHeadingId}
        className="break-inside-avoid p-4"
      >
        <h2
          id={incomeHeadingId}
          className="text-base font-semibold text-fg"
        >
          Income
        </h2>
        <div className="mt-2">
          <ScheduleELineTable
            caption={`Schedule E income lines for ${header.property_name}, tax year ${header.tax_year}`}
            lines={incomeLines}
          />
        </div>
      </Card>

      <Card
        as="section"
        role={sectionRole}
        aria-labelledby={expensesHeadingId}
        className="break-inside-avoid p-4"
      >
        <h2
          id={expensesHeadingId}
          className="text-base font-semibold text-fg"
        >
          Expenses
        </h2>
        <div className="mt-2">
          <ScheduleELineTable
            caption={`Schedule E expense lines for ${header.property_name}, tax year ${header.tax_year}`}
            lines={expenseLines}
          />
        </div>
      </Card>

      {/*
        Ranked expense-by-category chart (Req 16.1), placed directly below the
        expense section. Only rendered when there are expense rows so an empty
        report never shows an empty chart frame. The chart is lazy-loaded; the
        always-present data table is the mobile / error fallback (Req 12.1, 14).
      */}
      {expenseData.length > 0 && (
        <ChartCard
          title={`Expenses by category — ${header.property_name}`}
          ariaLabel={`Expenses by Schedule E category for ${header.property_name}, ranked highest to lowest`}
          chart={
            <LazyChart
              fallbackTable={<ExpenseByCategoryTable data={expenseData} />}
            >
              <ExpenseByCategoryChart data={expenseData} />
            </LazyChart>
          }
          dataTable={<ExpenseByCategoryTable data={expenseData} />}
        />
      )}

      <Card
        as="section"
        role={sectionRole}
        aria-labelledby={depreciationHeadingId}
        className="break-inside-avoid p-4"
      >
        <h2
          id={depreciationHeadingId}
          className="text-base font-semibold text-fg"
        >
          Depreciation (Line 18)
        </h2>
        <p className="mt-2 text-sm text-fg-muted">
          Total property depreciation for the year, computed from the
          depreciation schedules.
        </p>
        <p className="mt-1 text-sm">
          <span className="font-medium text-fg-muted">
            Line 18 depreciation:{" "}
          </span>
          <span className="tabular-nums text-fg">
            {formatMoney(depreciationLine?.total ?? "0.00")}
          </span>
        </p>
      </Card>

      <Card
        as="section"
        role={sectionRole}
        aria-labelledby={otherHeadingId}
        className="break-inside-avoid p-4"
      >
        <h2
          id={otherHeadingId}
          className="text-base font-semibold text-fg"
        >
          Other expenses (Line 19)
        </h2>
        {otherLine && (
          <p className="mt-1 text-sm">
            <span className="font-medium text-fg-muted">
              Line 19 total:{" "}
            </span>
            <span className="tabular-nums text-fg">
              {formatMoney(otherLine.total)}
            </span>
          </p>
        )}
        <div className="mt-2">
          <OtherItemsList
            caption={`Itemized Line 19 Other expenses for ${header.property_name}, tax year ${header.tax_year}`}
            items={other_items}
          />
        </div>
      </Card>

      <Card
        as="section"
        role={sectionRole}
        aria-labelledby={totalsHeadingId}
        className="break-inside-avoid p-4"
      >
        <h2
          id={totalsHeadingId}
          className="text-base font-semibold text-fg"
        >
          Totals
        </h2>
        <dl className="mt-3 space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <dt className="font-medium text-fg-muted">Total income</dt>
            <dd className="font-medium tabular-nums text-fg">
              {formatMoney(totals.total_income)}
            </dd>
          </div>
          <div className="flex items-center justify-between">
            <dt className="font-medium text-fg-muted">Total expenses</dt>
            <dd className="font-medium tabular-nums text-fg">
              {formatMoney(totals.total_expenses)}
            </dd>
          </div>
          <div className="flex items-baseline justify-between border-t-2 border-border pt-3">
            <dt className="text-lg font-bold text-fg">
              {netLoss ? "Net loss" : "Net income"}
            </dt>
            <dd
              className={[
                "text-xl font-bold tabular-nums",
                netLoss ? "text-danger" : "text-fg",
              ].join(" ")}
            >
              {formatMoney(totals.net)}
            </dd>
          </div>
        </dl>
      </Card>
    </div>
  );
}
