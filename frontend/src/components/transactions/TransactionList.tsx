import type { Category, Transaction } from "../../api/transactions";
import { formatMoney } from "../../lib/money";
import { ResponsiveTable, type ResponsiveTableColumn } from "../ui";

interface TransactionListProps {
  transactions: readonly Transaction[];
  categories: readonly Category[];
  /** id of the row whose receipts panel is expanded, if any. */
  expandedId: string | null;
  onEdit: (transaction: Transaction) => void;
  onDelete: (transaction: Transaction) => void;
  onToggleReceipts: (transaction: Transaction) => void;
  /** Rendered inside the expanded row (the receipts panel). */
  renderReceipts: (transaction: Transaction) => React.ReactNode;
}

const COLUMNS: ResponsiveTableColumn[] = [
  { key: "date", header: "Date" },
  { key: "type", header: "Type" },
  { key: "category", header: "Category" },
  { key: "amount", header: "Amount", align: "right" },
  { key: "description", header: "Description" },
  { key: "actions", header: "Actions" },
];

/**
 * Date-descending table of a property's transactions (Requirement 5.4). Rows
 * show date, type, category label + Schedule E line, amount, and description,
 * with per-row edit/delete (Requirements 5.6, 5.7) and a receipts toggle
 * (Requirement 5.8). Callers pass transactions already in date-descending
 * order; this component does not reorder.
 *
 * Layout is delegated to the shared {@link ResponsiveTable} primitive
 * (Requirement 6.3). Because that primitive uses a flat row model with no
 * nested expansion rows, the expanded receipts panel is rendered directly
 * below the table for whichever transaction is currently expanded.
 */
export function TransactionList({
  transactions,
  categories,
  expandedId,
  onEdit,
  onDelete,
  onToggleReceipts,
  renderReceipts,
}: TransactionListProps) {
  const categoryById = new Map(categories.map((c) => [c.id, c]));

  if (transactions.length === 0) {
    return (
      <p className="mt-4 text-fg-muted">
        No transactions yet. Add one to get started.
      </p>
    );
  }

  const rows = transactions.map((transaction) => {
    const category = categoryById.get(transaction.category_id);
    const isExpanded = expandedId === transaction.id;
    return {
      id: transaction.id,
      cells: {
        date: transaction.date,
        type: <span className="capitalize">{transaction.type}</span>,
        category: category
          ? `${category.label} (Line ${category.schedule_e_line})`
          : "Uncategorized",
        amount: (
          <span className="tabular-nums">
            {formatMoney(transaction.amount)}
          </span>
        ),
        description: (
          <span className="text-fg-muted">
            {transaction.description ?? ""}
          </span>
        ),
        actions: (
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={() => onToggleReceipts(transaction)}
              aria-expanded={isExpanded}
              className="rounded px-2 py-1 text-accent hover:bg-accent-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              Documents
            </button>
            <button
              type="button"
              onClick={() => onEdit(transaction)}
              className="rounded px-2 py-1 text-fg-muted hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              Edit
              <span className="sr-only"> transaction from {transaction.date}</span>
            </button>
            <button
              type="button"
              onClick={() => onDelete(transaction)}
              className="rounded px-2 py-1 text-danger hover:bg-danger-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              Delete
              <span className="sr-only"> transaction from {transaction.date}</span>
            </button>
          </div>
        ),
      },
    };
  });

  const expandedTransaction =
    expandedId != null
      ? transactions.find((t) => t.id === expandedId) ?? null
      : null;

  return (
    <div className="mt-4">
      <ResponsiveTable
        caption="Transactions ordered by date, newest first"
        columns={COLUMNS}
        rows={rows}
      />
      {expandedTransaction ? (
        <div className="mt-2 rounded border border-border bg-surface-muted px-2 py-2">
          {renderReceipts(expandedTransaction)}
        </div>
      ) : null}
    </div>
  );
}
