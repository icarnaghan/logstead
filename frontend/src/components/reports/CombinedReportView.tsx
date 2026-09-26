import { lazy } from "react";
import type { CombinedScheduleEReport } from "../../api/reports";
import { formatMoney, isLoss } from "../../lib/money";
import { Card } from "../ui";
import { ReportView } from "./ReportView";
import { ChartCard } from "../charts/ChartCard";
import { LazyChart } from "../charts/LazyChart";
import { combinedExpenseByCategory } from "../charts/prepare";
import { ExpenseByCategoryTable } from "../charts/ExpenseByCategoryTable";

/**
 * Portfolio-level expense-by-category chart, lazy-loaded so Recharts stays out
 * of the initial paint (Requirement 14). Reuses the same chart component as the
 * per-property report; the data is aggregated across every property here.
 */
const ExpenseByCategoryChart = lazy(
  () => import("../charts/ExpenseByCategoryChart"),
);

interface CombinedReportViewProps {
  /** The fetched combined, portfolio-level Schedule E report to render. */
  report: CombinedScheduleEReport;
}

/**
 * Renders the combined, portfolio-level Schedule E report (Requirements 10,
 * 16.2) as a hand-off document — numbers and forms, never a chart here.
 *
 * The portfolio totals (total income / total expenses / net, with the net
 * emphasized and a textual loss cue) lead the document, followed by each
 * property's full Schedule E report composed from the existing
 * {@link ReportView}. Each property report gets a unique heading and a unique
 * `idPrefix` so the composed sections keep valid, non-duplicated ids.
 *
 * The combined expense-by-category chart (task 17.1) is not added here; the
 * numbers-first totals section leaves a natural home for it above the
 * per-property breakdown.
 */
export function CombinedReportView({ report }: CombinedReportViewProps) {
  const { tax_year, properties, totals } = report;
  const netLoss = isLoss(totals.net);
  // Expense-by-category aggregated across all properties, ranked desc (Req 16.2).
  const combinedExpenseData = combinedExpenseByCategory(report);

  return (
    <div className="space-y-8">
      <Card
        as="section"
        aria-labelledby="combined-totals-heading"
        className="break-inside-avoid p-4"
      >
        <h2
          id="combined-totals-heading"
          className="text-base font-semibold text-fg"
        >
          Portfolio totals
        </h2>
        <p className="mt-1 text-sm text-fg-muted">
          Combined Schedule E across all properties for tax year {tax_year}.
        </p>
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

      {/*
        Per-property breakdown. Each property's Schedule E report is composed
        from the shared ReportView with a unique idPrefix so its section ids do
        not collide across properties.
      */}
      <section
        aria-labelledby="combined-properties-heading"
        className="space-y-8"
      >
        <h2
          id="combined-properties-heading"
          className="text-base font-semibold text-fg"
        >
          Properties
        </h2>

        {/*
          Portfolio-level ranked expense-by-category chart (Req 16.2),
          aggregated across every property. Only rendered when the portfolio has
          expense activity; the always-present data table is the mobile / error
          fallback (Req 12.1, 14).
        */}
        {combinedExpenseData.length > 0 && (
          <ChartCard
            title="Expenses by category (all properties)"
            ariaLabel="Portfolio expenses by Schedule E category across all properties, ranked highest to lowest"
            chart={
              <LazyChart
                fallbackTable={
                  <ExpenseByCategoryTable data={combinedExpenseData} />
                }
              >
                <ExpenseByCategoryChart data={combinedExpenseData} />
              </LazyChart>
            }
            dataTable={<ExpenseByCategoryTable data={combinedExpenseData} />}
          />
        )}

        {properties.length === 0 ? (
          <p className="text-sm text-fg-muted">
            No properties are included in this report.
          </p>
        ) : (
          properties.map((propertyReport, index) => {
            const prefix = `combined-report-${
              propertyReport.header.property_id || index
            }`;
            const headingId = `${prefix}-property-heading`;
            return (
              <div
                key={propertyReport.header.property_id || index}
                role="group"
                aria-labelledby={headingId}
                className="break-inside-avoid space-y-4"
              >
                <h3
                  id={headingId}
                  className="border-b border-border pb-1 text-sm font-semibold uppercase tracking-wide text-fg-muted"
                >
                  {propertyReport.header.property_name}
                </h3>
                <ReportView
                  report={propertyReport}
                  idPrefix={prefix}
                  region={false}
                />
              </div>
            );
          })
        )}
      </section>
    </div>
  );
}
