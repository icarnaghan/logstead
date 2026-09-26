import { Fragment } from "react";
import type { Category, Transaction } from "../../api/transactions";
import { formatMoney } from "./money";

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

/**
 * Date-descending table of a property's transactions (Requirement 5.4). Rows
 * show date, type, category label + Schedule E line, amount, and description,
 * with per-row edit/delete (Requirements 5.6, 5.7) and a receipts toggle
 * (Requirement 5.8). Callers pass transactions already in date-descending
 * order; this component does not reorder.
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

  return (
    <table className="mt-4 w-full border-collapse text-left text-sm">
      <caption className="sr-only">
        Transactions ordered by date, newest first
      </caption>
      <thead>
        <tr className="border-b border-border text-fg-subtle">
          <th scope="col" className="py-2 pr-4 font-medium">
            Date
          </th>
          <th scope="col" className="py-2 pr-4 font-medium">
            Type
          </th>
          <th scope="col" className="py-2 pr-4 font-medium">
            Category
          </th>
          <th scope="col" className="py-2 pr-4 text-right font-medium">
            Amount
          </th>
          <th scope="col" className="py-2 pr-4 font-medium">
            Description
          </th>
          <th scope="col" className="py-2 font-medium">
            <span className="sr-only">Actions</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {transactions.map((transaction) => {
          const category = categoryById.get(transaction.category_id);
          const isExpanded = expandedId === transaction.id;
          return (
            <Fragment key={transaction.id}>
              <tr className="border-b border-border align-top text-fg">
                <td className="py-2 pr-4">{transaction.date}</td>
                <td className="py-2 pr-4 capitalize">{transaction.type}</td>
                <td className="py-2 pr-4">
                  {category
                    ? `${category.label} (Line ${category.schedule_e_line})`
                    : transaction.category_id}
                </td>
                <td className="py-2 pr-4 text-right tabular-nums">
                  {formatMoney(transaction.amount)}
                </td>
                <td className="py-2 pr-4 text-fg-muted">
                  {transaction.description ?? ""}
                </td>
                <td className="py-2">
                  <div className="flex justify-end gap-2">
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
                      <span className="sr-only">
                        {" "}
                        transaction from {transaction.date}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(transaction)}
                      className="rounded px-2 py-1 text-danger hover:bg-danger-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    >
                      Delete
                      <span className="sr-only">
                        {" "}
                        transaction from {transaction.date}
                      </span>
                    </button>
                  </div>
                </td>
              </tr>
              {isExpanded ? (
                <tr className="border-b border-border bg-surface-muted">
                  <td colSpan={6} className="px-2 py-2">
                    {renderReceipts(transaction)}
                  </td>
                </tr>
              ) : null}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}
