import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Category, Transaction } from "../../api/transactions";
import { TransactionList } from "./TransactionList";

/**
 * Component tests for the transactions table's category rendering (task 7.7).
 *
 * When a transaction's `category_id` matches a known category, the row shows
 * the human-readable category label + Schedule E line (Requirement 3.3). When
 * it does not match any category, the row shows a human-readable fallback and
 * never the raw `category_id` (Requirement 3.4).
 *
 * Validates: Requirements 3.3, 3.4
 */

const CATEGORIES: Category[] = [
  {
    id: "cat-rent",
    kind: "income",
    label: "Rents received",
    schedule_e_line: "3",
    requires_description: false,
  },
];

function makeTransaction(overrides: Partial<Transaction> = {}): Transaction {
  return {
    id: "t1",
    property_id: "p1",
    date: "2024-01-15",
    amount: "1250.00",
    type: "income",
    category_id: "cat-rent",
    description: null,
    ...overrides,
  };
}

function renderList(transactions: readonly Transaction[]) {
  return render(
    <TransactionList
      transactions={transactions}
      categories={CATEGORIES}
      expandedId={null}
      onEdit={vi.fn()}
      onDelete={vi.fn()}
      onToggleReceipts={vi.fn()}
      renderReceipts={() => null}
    />,
  );
}

describe("TransactionList category rendering", () => {
  it("shows the category label and Schedule E line when the category is found", () => {
    renderList([makeTransaction({ category_id: "cat-rent" })]);
    // ResponsiveTable renders both a <table> and a card fallback, so the label
    // appears twice; scope the assertion to the table representation.
    const table = screen.getByRole("table");
    expect(
      within(table).getByText("Rents received (Line 3)"),
    ).toBeInTheDocument();
  });

  it("shows a human-readable fallback and never the raw category_id when unmatched", () => {
    const rawId = "cat-unknown-9f3a";
    renderList([makeTransaction({ category_id: rawId })]);

    const table = screen.getByRole("table");
    expect(within(table).getByText("Uncategorized")).toBeInTheDocument();
    // The machine identifier must never surface as user-facing content.
    expect(screen.queryByText(rawId)).not.toBeInTheDocument();
  });
});

describe("TransactionList responsive layout (Req 6.1, 6.2, 6.3)", () => {
  it("renders the desktop table and a card fallback container hidden at >= sm", () => {
    const { container } = renderList([makeTransaction()]);

    // The scroll-wrapped table is present at desktop widths.
    expect(screen.getByRole("table")).toBeInTheDocument();
    // ResponsiveTable also keeps a card list in the DOM, CSS-hidden at >= sm.
    expect(container.querySelector("ul.sm\\:hidden")).not.toBeNull();
  });

  it("renders the expanded receipts panel below the table for the expanded row", () => {
    render(
      <TransactionList
        transactions={[makeTransaction({ id: "t1" })]}
        categories={CATEGORIES}
        expandedId="t1"
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onToggleReceipts={vi.fn()}
        renderReceipts={(t) => <div>receipts for {t.id}</div>}
      />,
    );

    expect(screen.getByText("receipts for t1")).toBeInTheDocument();
  });
});
