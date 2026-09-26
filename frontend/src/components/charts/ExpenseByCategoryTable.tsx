import { centsToMoney, formatMoney } from "../../lib/money";
import type { CategoryDatum } from "./prepare";

/**
 * The always-present data table for the expense-by-category chart
 * (Requirements 12.1, 14, 16.3).
 *
 * This table lives in its **own module** — deliberately free of any Recharts
 * import — so it can be rendered eagerly wherever the chart appears (as the
 * `ChartCard` `dataTable` and the `LazyChart` `fallbackTable`) without dragging
 * the charting library into the initial bundle. The numbers are therefore never
 * gated by the lazy chart chunk: if the chart fails to load or the viewport is
 * below `sm`, this table is what the user sees.
 *
 * One row per category — Category | Amount — with amounts formatted from exact
 * integer cents (`formatMoney(centsToMoney(cents))`, Requirement 13.2) and
 * right-aligned with `tabular-nums`. Rows follow the incoming order, which is
 * already ranked descending by the caller (Requirement 16.3).
 */
export interface ExpenseByCategoryTableProps {
  /** Category slices, already ranked by descending cents (Req 16.3). */
  data: CategoryDatum[];
}

export function ExpenseByCategoryTable({ data }: ExpenseByCategoryTableProps) {
  if (data.length === 0) {
    return (
      <p className="text-sm text-fg-subtle">
        No expense categories have any activity for this report.
      </p>
    );
  }

  return (
    <table className="w-full border-collapse text-sm">
      <caption className="sr-only">
        Expenses by Schedule E category, ranked from highest to lowest amount.
      </caption>
      <thead>
        <tr className="border-b border-border text-left text-fg-muted">
          <th scope="col" className="py-1.5 pr-4 font-medium">
            Category
          </th>
          <th scope="col" className="py-1.5 text-right font-medium">
            Amount
          </th>
        </tr>
      </thead>
      <tbody>
        {data.map((datum) => (
          <tr key={datum.label} className="border-b border-border">
            <th scope="row" className="py-1.5 pr-4 font-normal text-fg">
              {datum.label}
            </th>
            <td className="py-1.5 text-right tabular-nums text-fg">
              {formatMoney(centsToMoney(datum.cents))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
