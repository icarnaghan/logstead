import type { Transaction } from "../../api/transactions";
import { formatMoney } from "../../lib/money";
import { ResponsiveTable, type ResponsiveTableColumn } from "../ui";

interface ItemizedEntryListProps {
  entries: readonly Transaction[];
  /** Singular noun for one entry, e.g. "repair". */
  entryNoun: string;
  /** id of the entry whose documents panel is expanded, if any. */
  expandedId: string | null;
  onEdit: (entry: Transaction) => void;
  onDelete: (entry: Transaction) => void;
  onToggleDocuments: (entry: Transaction) => void;
  /** Rendered below the table for the expanded entry (the receipts list). */
  renderReceipts: (entry: Transaction) => React.ReactNode;
}

const COLUMNS: ResponsiveTableColumn[] = [
  { key: "date", header: "Date" },
  { key: "description", header: "Description / vendor" },
  { key: "notes", header: "Notes" },
  { key: "amount", header: "Amount", align: "right" },
  { key: "actions", header: "Actions" },
];

const ACTION_BASE =
  "rounded px-2 py-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent max-md:min-h-11";

/**
 * Newest-first table of itemized entries (Requirements 2.10, 3.1, 16.6).
 * Callers pass entries already ordered; this component does not reorder.
 * Every row action names the entry by date and description.
 */
export function ItemizedEntryList({
  entries,
  entryNoun,
  expandedId,
  onEdit,
  onDelete,
  onToggleDocuments,
  renderReceipts,
}: ItemizedEntryListProps) {
  if (entries.length === 0) {
    return (
      <p className="mt-4 text-fg-muted">
        No itemized {entryNoun} entries for this year. Add one to keep detail
        behind the total.
      </p>
    );
  }

  const rows = entries.map((entry) => {
    const name = `${entry.description ?? entryNoun} from ${entry.date}`;
    return {
      id: entry.id,
      cells: {
        date: entry.date,
        description: entry.description ?? "",
        notes: <span className="text-fg-muted">{entry.notes ?? ""}</span>,
        amount: (
          <span className="tabular-nums">{formatMoney(entry.amount)}</span>
        ),
        actions: (
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={() => onToggleDocuments(entry)}
              aria-expanded={expandedId === entry.id}
              className={`${ACTION_BASE} text-accent hover:bg-accent-subtle`}
            >
              Documents
              <span className="sr-only"> for {name}</span>
            </button>
            <button
              type="button"
              onClick={() => onEdit(entry)}
              className={`${ACTION_BASE} text-fg-muted hover:bg-surface-muted`}
            >
              Edit
              <span className="sr-only"> {name}</span>
            </button>
            <button
              type="button"
              onClick={() => onDelete(entry)}
              className={`${ACTION_BASE} text-danger hover:bg-danger-subtle`}
            >
              Delete
              <span className="sr-only"> {name}</span>
            </button>
          </div>
        ),
      },
    };
  });

  const expanded =
    expandedId != null ? entries.find((e) => e.id === expandedId) ?? null : null;

  return (
    <div className="mt-4">
      <ResponsiveTable
        caption="Itemized entries ordered by date, newest first"
        columns={COLUMNS}
        rows={rows}
        focusableRows
      />
      {expanded ? (
        <div className="mt-2 rounded border border-border bg-surface-muted px-2 py-2">
          {renderReceipts(expanded)}
        </div>
      ) : null}
    </div>
  );
}
