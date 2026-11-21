import { centsToMoney, formatMoney } from "../../lib/money";
import type { DepreciationTrendDatum } from "./prepare";

/**
 * The always-present data table for the portfolio depreciation trend chart
 * (Requirements 5.1, 5.3, 10.1, 10.4).
 *
 * This table lives in its **own module** — deliberately free of any Recharts
 * import — so it can be rendered eagerly wherever the chart appears (as the
 * `ChartCard` `dataTable` and the `LazyChart` `fallbackTable`) without dragging
 * the charting library into the initial bundle. If the chart fails to load or
 * the viewport is below `sm`, this table is what the user sees.
 *
 * One row per Data_Year (ascending, in the caller's order) — Year | Depreciation
 * — with the portfolio Schedule E Line 18 total formatted from exact integer
 * cents (`formatMoney(centsToMoney(cents))`, Requirement 10.4) and right-aligned
 * with `tabular-nums`.
 */
export interface DepreciationTrendTableProps {
  /** Portfolio Line 18 depreciation total per Data_Year, ascending. */
  data: DepreciationTrendDatum[];
}

export function DepreciationTrendTable({ data }: DepreciationTrendTableProps) {
  if (data.length === 0) {
    return (
      <p className="text-sm text-fg-subtle">
        No depreciation to show across your properties yet.
      </p>
    );
  }

  return (
    <table className="w-full border-collapse text-sm">
      <caption className="sr-only">
        Portfolio depreciation total (Schedule E Line 18) by year.
      </caption>
      <thead>
        <tr className="border-b border-border text-left text-fg-muted">
          <th scope="col" className="py-1.5 pr-4 font-medium">
            Year
          </th>
          <th scope="col" className="py-1.5 text-right font-medium">
            Depreciation
          </th>
        </tr>
      </thead>
      <tbody>
        {data.map((datum) => (
          <tr key={datum.year} className="border-b border-border">
            <th scope="row" className="py-1.5 pr-4 font-normal text-fg">
              {datum.year}
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
