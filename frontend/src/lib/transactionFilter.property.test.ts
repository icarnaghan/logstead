import { describe, expect, it } from "vitest";
import fc from "fast-check";
import type { Category, Transaction } from "../api/transactions";
import { formatMoney } from "./money";
import { filterTransactions } from "./transactionFilter";

/**
 * Property-based tests for the transaction search and category filter
 * (task 32). Uses `fast-check` with 100 runs per property.
 */

const text = fc.string({ maxLength: 12 });

const amount: fc.Arbitrary<string> = fc
  .tuple(fc.integer({ min: 0, max: 99_999_999 }), fc.integer({ min: 0, max: 99 }))
  .map(([d, c]) => `${d}.${String(c).padStart(2, "0")}`);

interface Scenario {
  transactions: Transaction[];
  categories: Category[];
  query: string;
  categoryId: string | null;
}

/** Builds a list with categories, transactions, a query and a category pick. */
const scenario: fc.Arbitrary<Scenario> = fc
  .record({
    labels: fc.array(text, { minLength: 1, maxLength: 4 }),
    rows: fc.array(
      fc.record({
        catIndex: fc.nat(),
        amount,
        description: fc.option(text, { nil: null }),
      }),
      { maxLength: 12 },
    ),
    plant: fc.record({
      rowPick: fc.nat(),
      field: fc.constantFrom("description", "label", "amount", "formatted"),
      start: fc.nat(),
      len: fc.nat({ max: 6 }),
      upper: fc.boolean(),
      pad: fc.constantFrom("", " ", "  "),
    }),
    useRandomQuery: fc.boolean(),
    randomQuery: text,
    categoryPick: fc.option(fc.nat(), { nil: null }),
  })
  .map((r) => {
    const categories: Category[] = r.labels.map((label, i) => ({
      id: `cat-${i}`,
      kind: "expense",
      label,
      schedule_e_line: String(i),
      requires_description: false,
    }));
    const transactions: Transaction[] = r.rows.map((row, i) => ({
      id: `tx-${i}`,
      property_id: "p1",
      date: "2024-01-01",
      amount: row.amount,
      type: "expense",
      category_id: categories[row.catIndex % categories.length].id,
      description: row.description,
    }));

    let query = r.randomQuery;
    if (!r.useRandomQuery && transactions.length > 0) {
      // Plant a substring of a field of a randomly chosen transaction.
      const t = transactions[r.plant.rowPick % transactions.length];
      const label = categories.find((c) => c.id === t.category_id)!.label;
      const source =
        r.plant.field === "description"
          ? (t.description ?? "")
          : r.plant.field === "label"
            ? label
            : r.plant.field === "amount"
              ? t.amount
              : formatMoney(t.amount);
      const start = source.length === 0 ? 0 : r.plant.start % source.length;
      const piece = source.slice(start, start + r.plant.len);
      const cased = r.plant.upper ? piece.toUpperCase() : piece;
      query = `${r.plant.pad}${cased}${r.plant.pad}`;
    }

    const categoryId =
      r.categoryPick === null
        ? null
        : categories[r.categoryPick % categories.length].id;

    return { transactions, categories, query, categoryId };
  });

describe("transactionFilter properties", () => {
  it("Feature: ui-polish-and-consistency, Property 21: Filter results are exactly the matching transactions", () => {
    // **Validates: Requirements 21.2, 21.4, 21.7**
    fc.assert(
      fc.property(scenario, ({ transactions, categories, query, categoryId }) => {
        const result = filterTransactions(transactions, categories, {
          query,
          categoryId,
        });

        const needle = query.trim().toLowerCase();
        const labelOf = (id: string) =>
          categories.find((c) => c.id === id)?.label ?? "";
        const matches = (t: Transaction): boolean => {
          if (categoryId !== null && t.category_id !== categoryId) return false;
          return [
            t.description ?? "",
            labelOf(t.category_id),
            t.amount,
            formatMoney(t.amount),
          ].some((f) => f.toLowerCase().includes(needle));
        };

        // Every returned transaction matches both conditions.
        for (const t of result) expect(matches(t)).toBe(true);

        // Every matching input transaction is returned (no omissions).
        const expected = transactions.filter(matches);
        expect(result.map((t) => t.id)).toEqual(expected.map((t) => t.id));
      }),
      { numRuns: 100 },
    );
  });

  it("Feature: ui-polish-and-consistency, Property 22: Filters compose and never reorder", () => {
    // **Validates: Requirements 21.5, 21.6**
    fc.assert(
      fc.property(scenario, ({ transactions, categories, query, categoryId }) => {
        const ids = (list: Transaction[]) => list.map((t) => t.id);
        const both = filterTransactions(transactions, categories, {
          query,
          categoryId,
        });
        const byQuery = filterTransactions(transactions, categories, {
          query,
          categoryId: null,
        });
        const byCategory = filterTransactions(transactions, categories, {
          query: "",
          categoryId,
        });

        // Both filters equal the intersection of each alone.
        const queryIds = new Set(ids(byQuery));
        const categoryIds = new Set(ids(byCategory));
        const intersection = ids(transactions).filter(
          (id) => queryIds.has(id) && categoryIds.has(id),
        );
        expect(ids(both)).toEqual(intersection);

        // Empty query and no category returns every transaction.
        const all = filterTransactions(transactions, categories, {
          query: "",
          categoryId: null,
        });
        expect(ids(all)).toEqual(ids(transactions));

        // Result is a subsequence of the input (order preserved).
        const inputIds = ids(transactions);
        let cursor = 0;
        for (const id of ids(both)) {
          const found = inputIds.indexOf(id, cursor);
          expect(found).toBeGreaterThanOrEqual(0);
          cursor = found + 1;
        }
      }),
      { numRuns: 100 },
    );
  });
});
