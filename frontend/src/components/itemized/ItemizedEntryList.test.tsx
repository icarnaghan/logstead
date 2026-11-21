import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Transaction } from "../../api/transactions";
import { ItemizedEntryList } from "./ItemizedEntryList";

const E1: Transaction = {
  id: "e1",
  property_id: "p1",
  date: "2023-09-02",
  amount: "620.00",
  type: "expense",
  category_id: "repairs",
  description: "Plumber",
  notes: "Invoice 1182",
  itemized: true,
};
const E2: Transaction = { ...E1, id: "e2", date: "2023-01-05", amount: "80.5", description: "Paint", notes: null };

function setup(entries: Transaction[], expandedId: string | null = null) {
  const h = { onEdit: vi.fn(), onDelete: vi.fn(), onToggleDocuments: vi.fn() };
  render(
    <ItemizedEntryList
      entries={entries}
      entryNoun="repair"
      expandedId={expandedId}
      renderReceipts={(e) => <div>receipts for {e.id}</div>}
      {...h}
    />,
  );
  return h;
}

describe("ItemizedEntryList", () => {
  it("shows an empty message with no entries", () => {
    setup([]);
    expect(screen.getByText(/no itemized repair entries/i)).toBeInTheDocument();
  });

  it("keeps the given order and shows amounts in cents", () => {
    setup([E1, E2]);
    const dates = screen.getAllByText(/^2023-/).map((n) => n.textContent);
    expect(dates).toEqual(["2023-09-02", "2023-01-05"]);
    expect(screen.getByText("$620.00")).toBeInTheDocument();
    expect(screen.getByText("$80.50")).toBeInTheDocument();
    expect(screen.getByText("Invoice 1182")).toBeInTheDocument();
  });

  it("actions have accessible names with date and description", async () => {
    const user = userEvent.setup();
    const h = setup([E1]);
    await user.click(screen.getByRole("button", { name: "Edit Plumber from 2023-09-02" }));
    await user.click(screen.getByRole("button", { name: "Delete Plumber from 2023-09-02" }));
    await user.click(
      screen.getByRole("button", { name: "Documents for Plumber from 2023-09-02" }),
    );
    expect(h.onEdit).toHaveBeenCalledWith(E1);
    expect(h.onDelete).toHaveBeenCalledWith(E1);
    expect(h.onToggleDocuments).toHaveBeenCalledWith(E1);
  });

  it("renders receipts for the expanded entry only", () => {
    setup([E1, E2], "e2");
    expect(screen.getByText("receipts for e2")).toBeInTheDocument();
    expect(screen.queryByText("receipts for e1")).not.toBeInTheDocument();
  });
});
