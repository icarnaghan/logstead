import { lazy } from "react";
import { StateBlock, Tile } from "../ui";
import { formatMoney, isLoss } from "../../lib/money";
import { ChartCard } from "../charts/ChartCard";
import { LazyChart } from "../charts/LazyChart";
import { incomeExpenseNet } from "../charts/prepare";
import { IncomeExpenseNetTable } from "../charts/IncomeExpenseNetTable";
import type { ReportState } from "./reportState";

/**
 * The per-property income/expenses/net chart is the lazy boundary: Recharts is
 * reached only through this `React.lazy` import, so it code-splits into its own
 * async chunk absent from the initial paint (Requirement 14). The always-present
 * data table lives in a Recharts-free module imported eagerly above.
 */
const IncomeExpenseNetChart = lazy(
  () => import("../charts/IncomeExpenseNetChart"),
);

/** Income / expenses / net tile driven by the selected year's report. */
export function IncomeExpenseTile({ report }: { report: ReportState }) {
  return (
    <Tile title="Income & expenses (year-end)" headingId="tile-income">
      {report.status === "loading" ? (
        <p className="text-sm text-fg-subtle" role="status">
          Loading totals…
        </p>
      ) : report.status === "error" ? (
        <StateBlock
          kind="error"
          compact
          title="Could not load the report"
          description={report.message}
        />
      ) : report.status === "loaded" ? (
        <>
          <dl className="space-y-2">
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-sm text-fg-muted">Total income</dt>
              <dd className="tabular-nums font-semibold text-fg">
                {formatMoney(report.report.totals.total_income)}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-sm text-fg-muted">Total expenses</dt>
              <dd className="tabular-nums font-semibold text-fg">
                {formatMoney(report.report.totals.total_expenses)}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4 border-t border-border pt-2">
              <dt className="text-sm font-medium text-fg-muted">
                {isLoss(report.report.totals.net) ? "Net loss" : "Net income"}
              </dt>
              <dd
                className={[
                  "tabular-nums text-lg font-semibold",
                  isLoss(report.report.totals.net)
                    ? "text-danger"
                    : "text-success",
                ].join(" ")}
              >
                {formatMoney(report.report.totals.net)}
                {isLoss(report.report.totals.net) ? (
                  <span className="ml-2 align-middle text-xs font-medium uppercase tracking-wide text-danger">
                    Loss
                  </span>
                ) : null}
              </dd>
            </div>
          </dl>

          {/*
            Compact income / expenses / net chart for this property (Req 17.2),
            below the numbers. Lazy-loaded; the always-present data table is the
            mobile / error fallback (Req 12.1, 14).
          */}
          <div className="mt-4">
            {(() => {
              const chartData = incomeExpenseNet(report.report.totals);
              return (
                <ChartCard
                  title="Income, expenses & net"
                  ariaLabel="Income, expenses, and net for the selected year"
                  height={220}
                  chart={
                    <LazyChart
                      height={220}
                      fallbackTable={<IncomeExpenseNetTable data={chartData} />}
                    >
                      <IncomeExpenseNetChart data={chartData} />
                    </LazyChart>
                  }
                  dataTable={<IncomeExpenseNetTable data={chartData} />}
                />
              );
            })()}
          </div>
        </>
      ) : null}
    </Tile>
  );
}
