import { centsToMoney, formatMoney } from "../../lib/money";
import type { PropertyTrendSeries } from "./prepare";

/**
 * The always-present data table for the net-by-property **trend** chart
 * (Requirements 4.4, 10.1, 10.4).
 *
 * This table lives in its **own module** — deliberately free of any Recharts
 * import — so it can be rendered eagerly wherever the chart appears (as the
 * `ChartCard` `dataTable` and the `LazyChart` `fallbackTable`) without dragging
 * the charting library into the initial bundle. If the chart fails to load or
 * the viewport is below `sm`, this table is what the user sees.
 *
 * The chart carries one line **per property across the Data_Years**, so the
 * table pivots the series into one **row per Data_Year** (ascending) with one
 * **column per property series** (Requirement 4.1, 4.4). Column headers use the
 * caller-supplied unique labels (Requirement 4.5). Every amount is formatted
 * from exact integer cents (`formatMoney(centsToMoney(cents))`, Requirement
 * 10.4) and right-aligned with `tabular-nums`. A property missing a given year
 * contributes `0` cents from the backend's `0.00` (Requirement 4.2), so every
 * cell is always a two-decimal money string.
 */
export interface NetByPropertyTrendTableProps {
  /**
   * One series per owned property, each with a label unique across all series
   * and one point per Data_Year in ascending order (via `netByPropertyTrend`).
   */
  data: PropertyTrendSeries[];
}

export function NetByPropertyTrendTable({ data }: NetByPropertyTrendTableProps) {
  if (data.length === 0) {
    return (
      <p className="text-sm text-fg-subtle">
        No properties have any activity across these years.
      </p>
    );
  }

  // Every series carries one point per Data_Year in the same ascending order,
  // so the first series' points define the row (year) axis.
  const years = data[0].points.map((point) => point.year);

  if (years.length === 0) {
    return (
      <p className="text-sm text-fg-subtle">
        No years with activity to display.
      </p>
    );
  }

  return (
    <table className="w-full border-collapse text-sm">
      <caption className="sr-only">
        Net contribution per property for each year.
      </caption>
      <thead>
        <tr className="border-b border-border text-left text-fg-muted">
          <th scope="col" className="py-1.5 pr-4 font-medium">
            Year
          </th>
          {data.map((series) => (
            <th
              key={series.label}
              scope="col"
              className="py-1.5 pl-4 text-right font-medium"
            >
              {series.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {years.map((year, rowIndex) => (
          <tr key={year} className="border-b border-border">
            <th scope="row" className="py-1.5 pr-4 font-normal text-fg">
              {year}
            </th>
            {data.map((series) => {
              const cents = series.points[rowIndex]?.cents ?? 0;
              return (
                <td
                  key={series.label}
                  className="py-1.5 pl-4 text-right tabular-nums text-fg"
                >
                  {formatMoney(centsToMoney(cents))}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
