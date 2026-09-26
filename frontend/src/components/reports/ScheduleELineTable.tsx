import type { ReportLine } from "../../api/reports";
import { formatMoney } from "../../lib/money";

interface ScheduleELineTableProps {
  /** Accessible caption describing the table. */
  caption: string;
  /** The Schedule E line totals to render, in ascending line order. */
  lines: ReportLine[];
}

/**
 * Renders the per-line Schedule E totals as an accessible numeric table
 * (Requirement 10.1). Each row shows the Schedule E line number, its label,
 * whether it is an income or expense line, and the two-decimal total.
 *
 * This is deliberately a data table and never a chart — the initial release is
 * numbers-and-forms only. Money strings are formatted for display without any
 * arithmetic so no precision is lost.
 */
export function ScheduleELineTable({ caption, lines }: ScheduleELineTableProps) {
  if (lines.length === 0) {
    return (
      <p className="text-sm text-fg-subtle">
        No Schedule E lines have any activity for this tax year.
      </p>
    );
  }

  return (
    <table className="w-full border-collapse text-sm">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr className="border-b border-border text-left text-fg-muted">
          <th scope="col" className="py-1.5 pr-4 font-medium">
            Line
          </th>
          <th scope="col" className="py-1.5 pr-4 font-medium">
            Label
          </th>
          <th scope="col" className="py-1.5 pr-4 font-medium">
            Type
          </th>
          <th scope="col" className="py-1.5 text-right font-medium">
            Amount
          </th>
        </tr>
      </thead>
      <tbody>
        {lines.map((line) => (
          <tr key={line.line} className="border-b border-border">
            <th
              scope="row"
              className="py-1.5 pr-4 font-normal tabular-nums text-fg"
            >
              {line.line}
            </th>
            <td className="py-1.5 pr-4 text-fg">{line.label}</td>
            <td className="py-1.5 pr-4 capitalize text-fg-muted">
              {line.kind}
            </td>
            <td className="py-1.5 text-right tabular-nums text-fg">
              {formatMoney(line.total)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
