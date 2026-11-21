import { Fragment, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";
import { FOCUS_RING } from "./focusRing";
import { ChevronDownIcon, ChevronUpIcon, SortIcon } from "./icons";
import { TableSkeleton } from "./Skeleton";
import { nextSortState, sortRows } from "./tableSort";
import type { SortState, SortType } from "./tableSort";

export interface ResponsiveTableColumn {
  /** Key into each row's `cells` map. */
  key: string;
  /** Human-readable column label; reused as the card-layout field label. */
  header: string;
  /** Cell/column alignment; defaults to left. */
  align?: "left" | "right";
  /** Right aligned with tabular-nums, in header and body. */
  numeric?: boolean;
  /** Header renders a sort button. */
  sortable?: boolean;
  /** Comparison type for sorting; defaults to "text". */
  sortType?: SortType;
  /** Body cells render `<th scope="row">` instead of `<td>`. */
  rowHeader?: boolean;
}

export interface ResponsiveTableRow {
  /** Stable identity for the row. */
  id: string;
  /** Already-formatted cell content keyed by column key. */
  cells: Record<string, ReactNode>;
  /** Raw sort values; falls back to string or number cells. */
  sortValues?: Record<string, string | number | null>;
  /** Optional expandable detail content, rendered after the row. */
  detail?: ReactNode;
  /** Id of the detail row (table layout), for aria-controls. */
  detailId?: string;
  detailOpen?: boolean;
}

export interface ResponsiveTableProps {
  /** Accessible caption text (visually hidden). */
  caption: string;
  /** Column definitions, also used as the stacked-layout cell labels. */
  columns: ResponsiveTableColumn[];
  /** Row model with pre-formatted cell nodes. */
  rows: ResponsiveTableRow[];
  /** First load: render a TableSkeleton in place of rows (Requirement 8.6). */
  loading?: boolean;
  stickyHeader?: boolean;
  /** Max-height class for the sticky scroll area; default "max-h-[70dvh]". */
  maxHeightClass?: string;
  defaultSort?: SortState;
  /** Controlled sort state. */
  sort?: SortState;
  onSortChange?: (state: SortState) => void;
  /** Give each row `id="row-{id}"` and `tabIndex={-1}` so `focus` links can target it. */
  focusableRows?: boolean;
}

/**
 * Shared responsive-table layout primitive (Requirements 6.1, 6.2).
 *
 * Presentational only: callers pass already-formatted cell nodes (money via
 * formatMoney, action buttons, etc.). A single semantic `<table>` (visually
 * hidden `<caption>`) is rendered for every viewport, so there is one DOM, one
 * set of ids and one accessible tree:
 *
 * - At >= `sm`: a normal table inside an `overflow-x-auto` wrapper so wide
 *   tables stay reachable (Req 6.1).
 * - At < `sm`: CSS restyles each row into a card whose cells show
 *   label-over-value pairs, using each cell's `data-label` and `::before`
 *   (Req 6.2). Sortable columns stay available as a row of sort buttons.
 */
export function ResponsiveTable({
  caption,
  columns,
  rows,
  loading = false,
  stickyHeader = false,
  maxHeightClass = "max-h-[70dvh]",
  defaultSort = null,
  sort,
  onSortChange,
  focusableRows = false,
}: ResponsiveTableProps) {
  const [internalSort, setInternalSort] = useState<SortState>(defaultSort);
  const sortState = sort !== undefined ? sort : internalSort;

  const sortedRows = useMemo(
    () =>
      sortRows(
        rows,
        sortState,
        (row, key) => {
          const raw = row.sortValues?.[key];
          if (raw !== undefined) return raw;
          const cell = row.cells[key];
          return typeof cell === "string" || typeof cell === "number"
            ? cell
            : null;
        },
        (key) => columns.find((c) => c.key === key)?.sortType ?? "text",
      ),
    [rows, sortState, columns],
  );

  if (loading) {
    return <TableSkeleton columns={columns.length} />;
  }

  function toggleSort(key: string) {
    const next = nextSortState(sortState, key);
    if (sort === undefined) setInternalSort(next);
    onSortChange?.(next);
  }

  const right = (c: ResponsiveTableColumn) => c.numeric || c.align === "right";

  const hasSortable = columns.some((c) => c.sortable);

  return (
    <div
      className={cn(
        stickyHeader ? cn("overflow-auto", maxHeightClass) : "overflow-x-auto",
      )}
    >
      <table className="w-full border-collapse text-sm max-sm:block">
        <caption className="sr-only">{caption}</caption>
        {/* < sm: header labels move into each cell (data-label); the header row
            stays in the DOM for assistive tech and, when columns are sortable,
            shows as a row of sort buttons. */}
        <thead
          className={cn(
            "max-sm:block",
            !hasSortable && "max-sm:sr-only",
            hasSortable && "max-sm:mb-3",
          )}
        >
          <tr
            className={cn(
              "border-b border-border text-left text-fg-subtle",
              "max-sm:flex max-sm:flex-wrap max-sm:gap-2 max-sm:border-b-0",
            )}
          >
            {columns.map((column) => {
              const sorted =
                sortState && sortState.key === column.key
                  ? sortState.direction
                  : null;
              const Icon =
                sorted === "asc"
                  ? ChevronUpIcon
                  : sorted === "desc"
                    ? ChevronDownIcon
                    : SortIcon;
              return (
                <th
                  key={column.key}
                  scope="col"
                  aria-sort={
                    column.sortable && sorted
                      ? sorted === "asc"
                        ? "ascending"
                        : "descending"
                      : undefined
                  }
                  className={cn(
                    "py-2 pr-4 font-medium",
                    right(column) && "text-right",
                    column.numeric && "tabular-nums",
                    !column.sortable && "max-sm:sr-only",
                    stickyHeader &&
                      "sticky top-0 z-10 bg-surface shadow-[inset_0_-1px_0_rgb(var(--color-border))]",
                  )}
                >
                  {column.sortable ? (
                    <button
                      type="button"
                      onClick={() => toggleSort(column.key)}
                      className={cn(
                        "inline-flex items-center gap-1 rounded font-medium hover:text-fg max-md:min-h-11",
                        FOCUS_RING,
                        right(column) && "flex-row-reverse",
                      )}
                    >
                      <span>{column.header}</span>
                      <Icon aria-hidden="true" className="h-4 w-4" />
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="max-sm:block max-sm:space-y-3">
          {sortedRows.map((row) => (
            <Fragment key={row.id}>
              <tr
                id={focusableRows ? `row-${row.id}` : undefined}
                tabIndex={focusableRows ? -1 : undefined}
                className={cn(
                  "border-b border-border hover:bg-surface-muted focus-within:bg-surface-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  "max-sm:block max-sm:space-y-2 max-sm:rounded-lg max-sm:border max-sm:bg-surface max-sm:p-4 max-sm:shadow-card",
                )}
              >
                {columns.map((column) => {
                  const cls = cn(
                    "py-2 pr-4 text-fg",
                    right(column) && "text-right",
                    column.numeric && "tabular-nums",
                    "max-sm:block max-sm:py-0 max-sm:pr-0",
                    "max-sm:before:block max-sm:before:text-xs max-sm:before:font-medium max-sm:before:text-fg-subtle max-sm:before:content-[attr(data-label)]",
                  );
                  const content = row.cells[column.key];
                  return column.rowHeader ? (
                    <th
                      key={column.key}
                      scope="row"
                      data-label={column.header}
                      className={cn(cls, "text-left font-normal", right(column) && "text-right")}
                    >
                      {content}
                    </th>
                  ) : (
                    <td key={column.key} data-label={column.header} className={cls}>
                      {content}
                    </td>
                  );
                })}
              </tr>
              {row.detail !== undefined && row.detail !== null && (
                <tr
                  id={row.detailId}
                  hidden={!row.detailOpen}
                  className={cn(row.detailOpen && "max-sm:block")}
                >
                  <td
                    colSpan={columns.length}
                    className="pb-3 max-sm:block max-sm:pb-0"
                  >
                    {row.detail}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
