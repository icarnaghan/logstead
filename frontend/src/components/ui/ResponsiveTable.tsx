import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

export interface ResponsiveTableColumn {
  /** Key into each row's `cells` map. */
  key: string;
  /** Human-readable column label; reused as the card-layout field label. */
  header: string;
  /** Cell/column alignment; defaults to left. */
  align?: "left" | "right";
}

export interface ResponsiveTableRow {
  /** Stable identity for the row. */
  id: string;
  /** Already-formatted cell content keyed by column key. */
  cells: Record<string, ReactNode>;
}

export interface ResponsiveTableProps {
  /** Accessible caption text (visually hidden). */
  caption: string;
  /** Column definitions, also used for the card fallback labels. */
  columns: ResponsiveTableColumn[];
  /** Row model with pre-formatted cell nodes. */
  rows: ResponsiveTableRow[];
}

/**
 * Shared responsive-table layout primitive (Requirements 6.1, 6.2).
 *
 * Presentational only: callers pass already-formatted cell nodes (money via
 * formatMoney, action buttons, etc.). Two representations coexist in the DOM
 * and are shown/hidden purely via CSS breakpoints:
 *
 * - At >= `sm`: a real `<table>` (with a visually-hidden `<caption>` for
 *   assistive tech) inside an `overflow-x-auto` scroll wrapper so wide tables
 *   stay reachable without breaking layout (Req 6.1).
 * - At < `sm`: each row renders as a card-like block with `header: value`
 *   pairs using the column labels (Req 6.2), respecting each column's `align`.
 */
export function ResponsiveTable({
  caption,
  columns,
  rows,
}: ResponsiveTableProps) {
  return (
    <div>
      {/* >= sm: scroll-wrapped table */}
      <div className="hidden overflow-x-auto sm:block">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className="border-b border-border text-left text-fg-subtle">
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  className={cn(
                    "py-2 pr-4 font-medium",
                    column.align === "right" && "text-right",
                  )}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-b border-border">
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn(
                      "py-2 pr-4 text-fg",
                      column.align === "right" && "text-right",
                    )}
                  >
                    {row.cells[column.key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* < sm: card-per-row layout */}
      <ul className="space-y-3 sm:hidden">
        {rows.map((row) => (
          <li
            key={row.id}
            className="rounded-lg border border-border bg-surface p-4 shadow-card"
          >
            <dl className="space-y-2 text-sm">
              {columns.map((column) => (
                <div
                  key={column.key}
                  className="flex items-start justify-between gap-4"
                >
                  <dt className="font-medium text-fg-subtle">
                    {column.header}
                  </dt>
                  <dd
                    className={cn(
                      "text-fg",
                      column.align === "right" ? "text-right" : "text-left",
                    )}
                  >
                    {row.cells[column.key]}
                  </dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ul>
    </div>
  );
}
