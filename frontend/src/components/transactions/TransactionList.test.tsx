import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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
    <MemoryRouter>
    <TransactionList
      transactions={transactions}
      categories={CATEGORIES}
      expandedId={null}
      onEdit={vi.fn()}
      onDelete={vi.fn()}
      onToggleReceipts={vi.fn()}
      renderReceipts={() => null}
    />
    </MemoryRouter>,
  );
}

describe("TransactionList category rendering", () => {
  it("shows the category label and Schedule E line when the category is found", () => {
    renderList([makeTransaction({ category_id: "cat-rent" })]);
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
  it("renders a single table that also serves narrow viewports", () => {
    const { container } = renderList([makeTransaction()]);

    // The scroll-wrapped table is present at desktop widths.
    expect(screen.getByRole("table")).toBeInTheDocument();
    // One DOM serves both layouts: no separate card list.
    expect(container.querySelector("ul")).toBeNull();
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

describe("TransactionList itemized rows (Req 10.2)", () => {
  const itemized = makeTransaction({
    id: "t-item",
    type: "expense",
    category_id: "cat-rent",
    date: "2023-05-02",
    itemized: true,
  });

  it("shows an Itemized badge and a link to the Repairs page for the entry's year", () => {
    renderList([itemized]);
    expect(screen.getByText("Itemized")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /manage on repairs page/i });
    expect(link).toHaveAttribute("href", "/properties/p1/repairs?year=2023");
  });

  it("hides Edit and Delete for itemized rows but keeps them for others", () => {
    renderList([itemized, makeTransaction({ id: "t2", date: "2023-06-01" })]);
    expect(
      screen.getAllByRole("button", { name: /^edit transaction/i }),
    ).toHaveLength(1);
    expect(
      screen.getAllByRole("button", { name: /^delete transaction/i }),
    ).toHaveLength(1);
    expect(screen.getAllByText("Itemized")).toHaveLength(1);
    expect(screen.getAllByRole("link", { name: /manage on repairs/i })).toHaveLength(1);
  });
});
