import type { ScheduleRow } from "../../api/assets";

interface ScheduleTableProps {
  /** Accessible caption / heading describing which asset this schedule is for. */
  caption: string;
  rows: ScheduleRow[];
}

/**
 * Renders a depreciable asset's year-by-year straight-line / mid-month
 * depreciation schedule as an accessible numeric table (Requirement 9.4).
 *
 * This is deliberately a data table (year, depreciation amount, remaining
 * basis) and never a chart: the initial release is numbers-and-forms only.
 * Money values arrive as strings and are rendered verbatim to avoid any
 * floating-point drift.
 */
export function ScheduleTable({ caption, rows }: ScheduleTableProps) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-fg-subtle">
        No depreciation schedule is available for this asset.
      </p>
    );
  }

  return (
    <table className="mt-2 w-full border-collapse text-sm">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr className="border-b border-border text-left text-fg-muted">
          <th scope="col" className="py-1.5 pr-4 font-medium">
            Tax year
          </th>
          <th scope="col" className="py-1.5 pr-4 text-right font-medium">
            Depreciation amount
          </th>
          <th scope="col" className="py-1.5 text-right font-medium">
            Remaining basis
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.tax_year} className="border-b border-border">
            <th scope="row" className="py-1.5 pr-4 font-normal text-fg">
              {row.tax_year}
            </th>
            <td className="py-1.5 pr-4 text-right tabular-nums text-fg">
              {row.amount}
            </td>
            <td className="py-1.5 text-right tabular-nums text-fg">
              {row.remaining_basis}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
