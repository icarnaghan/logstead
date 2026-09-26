import { centsToMoney, formatMoney } from "../../lib/money";
import type { PropertyNetDatum } from "./prepare";

/**
 * The always-present data table for the net-by-property chart
 * (Requirements 12.1, 12.4, 13.2, 18).
 *
 * This table lives in its **own module** — deliberately free of any Recharts
 * import — so it can be rendered eagerly wherever the chart appears (as the
 * `ChartCard` `dataTable` and the `LazyChart` `fallbackTable`) without dragging
 * the charting library into the initial bundle. If the chart fails to load or
 * the viewport is below `sm`, this table is what the user sees.
 *
 * One row per property — Property | Net — with amounts formatted from exact
 * integer cents (`formatMoney(centsToMoney(cents))`, Requirement 13.2) and
 * right-aligned with `tabular-nums`. Rows follow the incoming order, which is
 * already ranked descending by the caller (Requirement 18.2). A loss carries a
 * **textual** "(loss)" cue, so meaning never depends on color alone
 * (Requirement 12.4).
 */
export interface NetByPropertyTableProps {
  /** Per-property net figures, already ranked by descending cents (Req 18.2). */
  data: PropertyNetDatum[];
}

export function NetByPropertyTable({ data }: NetByPropertyTableProps) {
  if (data.length === 0) {
    return (
      <p className="text-sm text-fg-subtle">
        No properties have any activity for this year.
      </p>
    );
  }

  return (
    <table className="w-full border-collapse text-sm">
      <caption className="sr-only">
        Net contribution by property, ranked from highest to lowest.
      </caption>
      <thead>
        <tr className="border-b border-border text-left text-fg-muted">
          <th scope="col" className="py-1.5 pr-4 font-medium">
            Property
          </th>
          <th scope="col" className="py-1.5 text-right font-medium">
            Net
          </th>
        </tr>
      </thead>
      <tbody>
        {data.map((datum) => {
          const loss = datum.cents < 0;
          return (
            <tr key={datum.label} className="border-b border-border">
              <th scope="row" className="py-1.5 pr-4 font-normal text-fg">
                {datum.label}
              </th>
              <td className="py-1.5 text-right tabular-nums text-fg">
                {formatMoney(centsToMoney(datum.cents))}
                {loss ? (
                  <span className="ml-1 text-xs font-medium uppercase tracking-wide text-fg-muted">
                    {" "}
                    (loss)
                  </span>
                ) : null}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
