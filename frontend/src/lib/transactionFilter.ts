/**
 * Pure transaction search and category filter (Requirements 21.2, 21.4, 21.5,
 * 21.6, 21.10). Runs on the already loaded list; input order is preserved.
 */

import type { Category, Transaction } from "../api/transactions";
import { formatMoney } from "./money";

export interface TransactionFilter {
  query: string;
  categoryId: string | null;
}

/**
 * Filters `transactions` by a free-text query and an optional category.
 *
 * The trimmed, lower-cased query must be a substring of the description, the
 * category label, the raw amount text, or the `formatMoney` text. An empty
 * query matches everything. `categoryId` of null matches every category.
 */
export function filterTransactions(
  transactions: readonly Transaction[],
  categories: readonly Category[],
  filter: TransactionFilter,
): Transaction[] {
  const query = filter.query.trim().toLowerCase();
  const labels = new Map<string, string>();
  for (const c of categories) labels.set(c.id, c.label);

  return transactions.filter((t) => {
    if (filter.categoryId !== null && t.category_id !== filter.categoryId) {
      return false;
    }
    if (query === "") return true;
    const fields = [
      t.description ?? "",
      labels.get(t.category_id) ?? "",
      t.amount,
      formatMoney(t.amount),
    ];
    return fields.some((f) => f.toLowerCase().includes(query));
  });
}
