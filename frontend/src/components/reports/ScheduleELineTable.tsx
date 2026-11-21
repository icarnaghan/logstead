import type { Line12Detail, ReportLine } from "../../api/reports";
import { formatMoney, formatMoneyWholeDollars } from "../../lib/money";
import { Badge } from "../ui";

const LINE_12 = 12;

interface ScheduleELineTableProps {
  /** Accessible caption describing the table. */
  caption: string;
  /** The Schedule E line totals to render, in ascending line order. */
  lines: ReportLine[];
  /**
   * Where Line 12 came from (Requirements 10.1-10.5). Missing or an
   * unrecognized `source` shows a "source unavailable" indication.
   */
  line12?: Line12Detail | null;
}

/** Label, badge, and superseded-amount text for the Line 12 row only. */
function renderLine12Note(line12: Line12Detail | null | undefined) {
  const source = line12?.source;
  if (source === "transaction-entered") return null;

  if (line12 && source === "loan-generated") {
    const { amount, count } = line12.superseded_manual_interest ?? {
      amount: "0.00",
      count: 0,
    };
    const showSuperseded = count > 0 || Number(amount) > 0;
    return (
      <>
        <Badge>Loan-generated</Badge>
        {showSuperseded ? (
          <span className="tabular-nums text-fg-muted">
            {`Superseded manual interest: ${formatMoney(amount)} (${count} transactions)`}
          </span>
        ) : null}
      </>
    );
  }

  return <span className="text-fg-muted">Line 12 source unavailable</span>;
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
export function ScheduleELineTable({
  caption,
  lines,
  line12,
}: ScheduleELineTableProps) {
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
            <td className="py-1.5 pr-4 text-fg">
              <span className="flex flex-wrap items-center gap-2">
                {line.label}
                {line.includes_imported ? (
                  <Badge label="Includes imported Schedule E amounts">
                    Imported
                  </Badge>
                ) : null}
                {line.line === LINE_12 ? renderLine12Note(line12) : null}
              </span>
            </td>
            <td className="py-1.5 pr-4 capitalize text-fg-muted">
              {line.kind}
            </td>
            <td className="py-1.5 text-right tabular-nums text-fg">
              {formatMoneyWholeDollars(line.total)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
