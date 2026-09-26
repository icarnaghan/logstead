import { centsToMoney, formatMoney } from "../../lib/money";
import type { IncomeExpenseNetDatum } from "./prepare";

/**
 * The always-present data table for the income / expenses / net chart
 * (Requirements 12.1, 12.4, 13.2, 17).
 *
 * This table lives in its **own module** — deliberately free of any Recharts
 * import — so it can be rendered eagerly wherever the chart appears (as the
 * `ChartCard` `dataTable` and the `LazyChart` `fallbackTable`) without dragging
 * the charting library into the initial bundle. If the chart fails to load or
 * the viewport is below `sm`, this table is what the user sees.
 *
 * Three rows — Income, Expenses, Net — with amounts formatted from exact
 * integer cents (`formatMoney(centsToMoney(cents))`, Requirement 13.2) and
 * right-aligned with `tabular-nums`. The Net row carries a **textual** gain /
 * loss cue ("income" vs. "loss"), so meaning never depends on color alone
 * (Requirement 12.4).
 */
export interface IncomeExpenseNetTableProps {
  /** The three portfolio / property figures in Income / Expenses / Net order. */
  data: IncomeExpenseNetDatum[];
}

/** The Net datum's textual gain/loss cue — never color alone (Req 12.4). */
function netCue(cents: number): string {
  return cents < 0 ? "loss" : "income";
}

export function IncomeExpenseNetTable({ data }: IncomeExpenseNetTableProps) {
  return (
    <table className="w-full border-collapse text-sm">
      <caption className="sr-only">
        Income, expenses, and net for the selected year.
      </caption>
      <thead>
        <tr className="border-b border-border text-left text-fg-muted">
          <th scope="col" className="py-1.5 pr-4 font-medium">
            Figure
          </th>
          <th scope="col" className="py-1.5 text-right font-medium">
            Amount
          </th>
        </tr>
      </thead>
      <tbody>
        {data.map((datum) => {
          const isNet = datum.key === "Net";
          return (
            <tr key={datum.key} className="border-b border-border">
              <th scope="row" className="py-1.5 pr-4 font-normal text-fg">
                {datum.key}
                {isNet ? (
                  <span className="ml-2 text-xs font-medium uppercase tracking-wide text-fg-muted">
                    ({netCue(datum.cents)})
                  </span>
                ) : null}
              </th>
              <td className="py-1.5 text-right tabular-nums text-fg">
                {formatMoney(centsToMoney(datum.cents))}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
