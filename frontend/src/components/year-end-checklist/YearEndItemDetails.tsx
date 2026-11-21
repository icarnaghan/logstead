import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { formatMoney } from "../../lib/money";
import {
  ResponsiveTable,
  type ResponsiveTableColumn,
  type ResponsiveTableRow,
} from "../ui";
import { linkLabel } from "./yearEndText";

type Details = Record<string, unknown>;
type ValueKind = "money" | "text" | "count";

interface ScalarSpec {
  readonly key: string;
  readonly label: string;
  readonly kind: ValueKind;
}

interface ListSpec {
  readonly key: string;
  readonly caption: string;
  readonly columns: readonly ColumnSpec[];
}

interface ColumnSpec {
  readonly key: string;
  readonly header: string;
  readonly kind: ValueKind | "percent" | "bool" | "link";
}

interface ItemSpec {
  readonly scalars: readonly ScalarSpec[];
  readonly list?: ListSpec;
}

const NONE_TEXT = "None";

const SPECS: Record<string, ItemSpec> = {
  income_entered: {
    scalars: [{ key: "income_total", label: "Income total", kind: "money" }],
  },
  expenses_entered: {
    scalars: [
      { key: "expense_total", label: "Expense total (excluding line 18)", kind: "money" },
    ],
  },
  depreciation_present: {
    scalars: [
      { key: "assets_with_schedule_rows", label: "Assets with a schedule row", kind: "count" },
      { key: "line_18_total", label: "Line 18 total", kind: "money" },
    ],
  },
  line12_source: {
    scalars: [
      { key: "source", label: "Source", kind: "text" },
      { key: "line_12_total", label: "Line 12 total", kind: "money" },
      { key: "superseded_count", label: "Superseded manual entries", kind: "count" },
      { key: "superseded_amount", label: "Superseded manual amount", kind: "money" },
    ],
  },
  loan_interest_confirmed: {
    scalars: [],
    list: {
      key: "loans",
      caption: "Loans evaluated for interest",
      columns: [
        { key: "name", header: "Loan", kind: "text" },
        { key: "confirmed", header: "Confirmed", kind: "bool" },
        { key: "anchor_date", header: "Balance anchor date", kind: "text" },
        { key: "interest", header: "Interest used", kind: "money" },
      ],
    },
  },
  carryforward_reconciled: {
    scalars: [
      { key: "status", label: "Status", kind: "text" },
      { key: "reported_carry_in", label: "Reported carry-in", kind: "money" },
      { key: "expected_carry_in", label: "Expected carry-in", kind: "money" },
      { key: "drift", label: "Drift", kind: "money" },
      { key: "carried_from_year", label: "Carried from year", kind: "text" },
      { key: "status_tolerance", label: "Status tolerance", kind: "money" },
    ],
  },
  repairs_exceed_total: {
    scalars: [
      { key: "entered_total", label: "Entered total", kind: "money" },
      { key: "itemized_sum", label: "Itemized sum", kind: "money" },
      { key: "remainder", label: "Remainder", kind: "money" },
      { key: "line_source", label: "Line source", kind: "text" },
    ],
  },
  repairs_capital_candidates: {
    scalars: [{ key: "flagged_count", label: "Entries to review", kind: "count" }],
    list: {
      key: "entries",
      caption: "Large repairs entries to review",
      columns: [
        { key: "date", header: "Date", kind: "text" },
        { key: "description", header: "Description", kind: "text" },
        { key: "amount", header: "Amount", kind: "money" },
        { key: "link", header: "Open", kind: "link" },
      ],
    },
  },
  receipts_missing: {
    scalars: [
      { key: "missing_count", label: "Without a receipt", kind: "count" },
      { key: "evaluated_count", label: "Evaluated", kind: "count" },
      { key: "shown_count", label: "Shown below", kind: "count" },
    ],
    list: {
      key: "transactions",
      caption: "Large expenses without a receipt",
      columns: [
        { key: "date", header: "Date", kind: "text" },
        { key: "category", header: "Category", kind: "text" },
        { key: "description", header: "Description", kind: "text" },
        { key: "amount", header: "Amount", kind: "money" },
      ],
    },
  },
  yoy_swings: {
    scalars: [{ key: "swing_count", label: "Lines with a change to review", kind: "count" }],
    list: {
      key: "lines",
      caption: "Year-over-year changes by Schedule E line",
      columns: [
        { key: "line", header: "Line", kind: "text" },
        { key: "label", header: "Label", kind: "text" },
        { key: "prior_total", header: "Prior year", kind: "money" },
        { key: "current_total", header: "This year", kind: "money" },
        { key: "change", header: "Change", kind: "money" },
        { key: "percent", header: "Change %", kind: "percent" },
      ],
    },
  },
  imported_values_edited: {
    scalars: [{ key: "edited_count", label: "Edited imported lines", kind: "count" }],
    list: {
      key: "rows",
      caption: "Imported values edited after import",
      columns: [
        { key: "schedule_e_line", header: "Schedule E line", kind: "text" },
        { key: "amount", header: "Amount", kind: "money" },
        { key: "updated_at", header: "Last edited", kind: "text" },
      ],
    },
  },
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Text for one wire value, or `null` when the value has an unexpected shape. */
function formatValue(value: unknown, kind: ValueKind | "percent" | "bool"): string | null {
  if (value === null || value === undefined) return NONE_TEXT;
  if (kind === "money") {
    return typeof value === "string" ? formatMoney(value) : null;
  }
  if (kind === "percent") {
    return typeof value === "string" || typeof value === "number" ? `${value}%` : null;
  }
  if (kind === "bool") {
    return typeof value === "boolean" ? (value ? "Yes" : "No") : null;
  }
  if (typeof value === "string" || typeof value === "number") return String(value);
  return null;
}

function isKnownLink(value: unknown): value is string {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//");
}

function cellFor(row: Record<string, unknown>, column: ColumnSpec): ReactNode | null {
  const value = row[column.key];
  if (column.kind === "link") {
    if (!isKnownLink(value)) return null;
    return <Link to={value}>{linkLabel(value)}</Link>;
  }
  return formatValue(value, column.kind);
}

function buildScalars(details: Details, specs: readonly ScalarSpec[]) {
  const items: { label: string; text: string }[] = [];
  for (const spec of specs) {
    if (!(spec.key in details)) continue;
    const text = formatValue(details[spec.key], spec.kind);
    if (text === null) continue;
    items.push({ label: spec.label, text });
  }
  return items;
}

function buildRows(details: Details, list: ListSpec): ResponsiveTableRow[] | null {
  const raw = details[list.key];
  if (!Array.isArray(raw)) return null;
  const rows: ResponsiveTableRow[] = [];
  for (const [index, entry] of raw.entries()) {
    if (!isRecord(entry)) return null;
    const cells: Record<string, ReactNode> = {};
    for (const column of list.columns) {
      const cell = cellFor(entry, column);
      if (cell === null) return null;
      cells[column.key] = cell;
    }
    const id = typeof entry.id === "string" ? entry.id : `${list.key}-${index}`;
    rows.push({ id, cells });
  }
  return rows;
}

function toColumns(list: ListSpec): ResponsiveTableColumn[] {
  return list.columns.map((column) => ({
    key: column.key,
    header: column.header,
    numeric: column.kind === "money" || column.kind === "percent",
    align: column.kind === "money" || column.kind === "percent" ? "right" : "left",
  }));
}

/**
 * Renders a checklist item's `details` for its item id: a definition list for
 * scalar values and a `ResponsiveTable` for row lists. Money goes through
 * `formatMoney`; nothing is computed. An unknown item id or a shape that does
 * not match renders nothing, so unexpected details cannot break the page.
 */
export function YearEndItemDetails({
  itemId,
  details,
}: {
  itemId: string;
  details: Record<string, unknown> | null | undefined;
}) {
  if (!isRecord(details)) return null;
  const spec = SPECS[itemId];
  if (!spec) return null;

  const scalars = buildScalars(details, spec.scalars);
  const rows = spec.list ? buildRows(details, spec.list) : null;
  const showTable = spec.list !== undefined && rows !== null && rows.length > 0;

  if (scalars.length === 0 && !showTable) return null;

  return (
    <div className="space-y-3">
      {scalars.length > 0 ? (
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
          {scalars.map((item) => (
            <div key={item.label} className="flex justify-between gap-4">
              <dt className="text-fg-muted">{item.label}</dt>
              <dd className="tabular-nums text-fg">{item.text}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {showTable && spec.list && rows ? (
        <ResponsiveTable
          caption={spec.list.caption}
          columns={toColumns(spec.list)}
          rows={rows}
        />
      ) : null}
    </div>
  );
}
