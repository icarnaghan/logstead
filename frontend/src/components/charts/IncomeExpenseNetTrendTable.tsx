import { centsToMoney, formatMoney } from "../../lib/money";
import type { TrendPointDatum } from "./prepare";

/**
 * The always-present data table for the portfolio income / expenses / net
 * **trend** chart (Requirements 3.1, 3.3, 3.4, 10.1, 10.4).
 *
 * This table lives in its **own module** — deliberately free of any Recharts
 * import — so it can be rendered eagerly wherever the chart appears (as the
 * `ChartCard` `dataTable` and the `LazyChart` `fallbackTable`) without dragging
 * the charting library into the initial bundle. If the chart fails to load or
 * the viewport is below `sm`, this table is what the user sees.
 *
 * One row per Data_Year in ascending chronological order (the order the caller
 * supplies via `incomeExpenseNetTrend` in `prepare.ts`), each carrying that
 * year's portfolio income, expenses, and net. Amounts are formatted from exact
 * integer cents (`formatMoney(centsToMoney(cents))`, Requirement 10.4) and
 * right-aligned with `tabular-nums`. Where a year's net is negative, the row
 * carries a **textual** loss cue ("loss"), so meaning never depends on color
 * alone (Requirement 3.4).
 */
export interface IncomeExpenseNetTrendTableProps {
  /** One point per Data_Year, in ascending chronological order (Req 3.1). */
  data: TrendPointDatum[];
}

/** The net column's textual gain/loss cue — never color alone (Req 3.4). */
function netCue(cents: number): string {
  return cents < 0 ? "loss" : "income";
}

/** Render integer cents as a US-currency string (Req 10.4). */
function formatCents(cents: number): string {
  return formatMoney(centsToMoney(cents));
}

export function IncomeExpenseNetTrendTable({
  data,
}: IncomeExpenseNetTrendTableProps) {
  return (
    <table className="w-full border-collapse text-sm">
      <caption className="sr-only">
        Portfolio income, expenses, and net for every year with data.
      </caption>
      <thead>
        <tr className="border-b border-border text-left text-fg-muted">
          <th scope="col" className="py-1.5 pr-4 font-medium">
            Year
          </th>
          <th scope="col" className="py-1.5 pr-4 text-right font-medium">
            Income
          </th>
          <th scope="col" className="py-1.5 pr-4 text-right font-medium">
            Expenses
          </th>
          <th scope="col" className="py-1.5 text-right font-medium">
            Net
          </th>
        </tr>
      </thead>
      <tbody>
        {data.map((datum) => (
          <tr key={datum.year} className="border-b border-border">
            <th scope="row" className="py-1.5 pr-4 font-normal text-fg">
              {datum.year}
            </th>
            <td className="py-1.5 pr-4 text-right tabular-nums text-fg">
              {formatCents(datum.income)}
            </td>
            <td className="py-1.5 pr-4 text-right tabular-nums text-fg">
              {formatCents(datum.expenses)}
            </td>
            <td className="py-1.5 text-right tabular-nums text-fg">
              {formatCents(datum.net)}
              {datum.net < 0 ? (
                <span className="ml-2 text-xs font-medium uppercase tracking-wide text-fg-muted">
                  ({netCue(datum.net)})
                </span>
              ) : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
