import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Transaction } from "../../api/transactions";
import { EnteredTotalCard } from "./EnteredTotalCard";

function row(id: string, over: Partial<Transaction> = {}): Transaction {
  return {
    id,
    property_id: "p1",
    date: "2023-12-31",
    amount: "4200.00",
    type: "expense",
    category_id: "repairs",
    description: null,
    ...over,
  };
}

function setup(rows: Transaction[], documentsExpanded = false) {
  const handlers = {
    onSet: vi.fn(),
    onEdit: vi.fn(),
    onRemove: vi.fn(),
    onToggleDocuments: vi.fn(),
  };
  render(
    <MemoryRouter>
      <EnteredTotalCard
        propertyId="p1"
        taxYear={2023}
        label="Repairs"
        line={14}
        rows={rows}
        documentsExpanded={documentsExpanded}
        renderReceipts={() => <div>receipts panel</div>}
        {...handlers}
      />
    </MemoryRouter>,
  );
  return handlers;
}

describe("EnteredTotalCard", () => {
  it("offers Set total when there is no row", async () => {
    const user = userEvent.setup();
    const h = setup([]);
    await user.click(screen.getByRole("button", { name: "Set total" }));
    expect(h.onSet).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Edit total" })).toBeNull();
  });

  it("single row: Edit, Remove and Documents act on the row", async () => {
    const user = userEvent.setup();
    const r = row("t1");
    const h = setup([r]);
    expect(screen.getByText("$4,200.00")).toBeInTheDocument();
    expect(screen.queryByText("Imported")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit total" }));
    await user.click(screen.getByRole("button", { name: "Remove total" }));
    await user.click(screen.getByRole("button", { name: /documents/i }));
    expect(h.onEdit).toHaveBeenCalledWith(r);
    expect(h.onRemove).toHaveBeenCalledWith(r);
    expect(h.onToggleDocuments).toHaveBeenCalledWith(r);
  });

  it("renders the receipts panel when expanded", () => {
    setup([row("t1")], true);
    expect(screen.getByText("receipts panel")).toBeInTheDocument();
  });

  it("imported row shows the badge and re-import hint", () => {
    setup([row("t1", { imported: true })]);
    expect(screen.getByText("Imported")).toBeInTheDocument();
    expect(
      screen.getByText(/re-importing a schedule e for 2023 replaces this imported total/i),
    ).toBeInTheDocument();
  });

  it("several rows: explanation, link, disabled actions", () => {
    setup([row("t1"), row("t2", { amount: "10.00" })]);
    expect(screen.getByText(/2 repairs total rows for 2023/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /transactions page/i })).toHaveAttribute(
      "href",
      "/properties/p1/transactions?year=2023",
    );
    expect(screen.getByRole("button", { name: "Edit total" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove total" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Set total" })).toBeNull();
  });
});
