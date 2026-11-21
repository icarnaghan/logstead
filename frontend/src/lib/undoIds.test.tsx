import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../components/ui/toast/ToastProvider";
import { useUndoableDelete } from "../components/ui/toast/useUndoableDelete";
import type { DepreciableAsset } from "../api/assets";
import type { Loan } from "../api/loans";
import type { Transaction } from "../api/transactions";
import {
  assetToInput,
  isItemizedEntrySafeDelete,
  isLoanSafeDelete,
  isTransactionSafeDelete,
  itemizedEntryToInput,
  loanToInput,
  transactionToInput,
} from "./undoMappers";

/**
 * Undo re-creates a record through the create API, so the server assigns a new
 * id (task 6.6, review R11). See "Undo and record IDs" in docs/developer-guide.md.
 */

const TXN = {
  id: "old-txn",
  property_id: "p1",
  date: "2024-03-01",
  amount: "10.00",
  type: "expense",
  category_id: "c1",
  description: "x",
  imported: false,
} as unknown as Transaction;

const ASSET = {
  id: "old-asset",
  description: "Roof",
  cost_basis: "1000.00",
  placed_in_service_date: "2020-01-01",
  recovery_period_years: 27.5,
  created_at: "t",
  updated_at: "t",
} as DepreciableAsset;

const LOAN = {
  id: "old-loan",
  property_id: "p1",
  description: "Mortgage",
  annual_interest_rate: "6.000",
  monthly_payment: "100.00",
  anchor_balance: "1000.00",
  anchor_date: "2024-01-01",
  extra_principal: "0.00",
  payoff_date: null,
  original_principal: null,
  closing_date: null,
  include_in_report: true,
  interest_overrides: {},
} as unknown as Loan;

describe("Undo and record IDs (R11)", () => {
  it("create payloads never carry the old id, property id or timestamps", () => {
    for (const payload of [
      transactionToInput(TXN),
      assetToInput(ASSET),
      loanToInput(LOAN),
    ]) {
      const keys = Object.keys(payload);
      for (const k of ["id", "property_id", "created_at", "updated_at"]) {
        expect(keys).not.toContain(k);
      }
    }
  });

  it("refreshes after restore so the UI lists the record under its new id", async () => {
    let rows = [{ id: "old" }];
    const refresh = vi.fn(async () => {});
    const seenAfterRestore: string[][] = [];
    function Harness() {
      const run = useUndoableDelete<{ id: string }>({
        remove: async () => {
          rows = [];
        },
        restore: async () => {
          rows = [{ id: "new" }];
        },
        refresh: () => {
          seenAfterRestore.push(rows.map((r) => r.id));
          return refresh();
        },
        deletedTitle: () => "Deleted",
        restoredTitle: "Restored",
        restoreFailedTitle: "Restore failed",
        deleteFailedTitle: "Delete failed",
      });
      return (
        <button type="button" onClick={() => void run({ id: "old" })}>
          Go
        </button>
      );
    }
    render(
      <ToastProvider>
        <Harness />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    await screen.findByText("Deleted");
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await screen.findByText("Restored");
    // First refresh (after delete) sees nothing; second (after Undo) sees only the new id.
    expect(seenAfterRestore).toEqual([[], ["new"]]);
  });

  it("deletes whose children Undo cannot restore are not undoable (limitation surfaced via confirm dialog)", () => {
    // Receipts: any count, or an unknown one, is never safe.
    expect(isTransactionSafeDelete(TXN, 1)).toBe(false);
    expect(isTransactionSafeDelete(TXN, null)).toBe(false);
    expect(isTransactionSafeDelete(TXN, 0)).toBe(true);
    // Imported rows cannot be re-created with the imported marker.
    expect(isTransactionSafeDelete({ ...TXN, imported: true }, 0)).toBe(false);
    // Loan yearly interest overrides are child rows.
    expect(
      isLoanSafeDelete({ ...LOAN, interest_overrides: { "2024": "1.00" } }),
    ).toBe(false);
    expect(isLoanSafeDelete(LOAN)).toBe(true);
  });

  it("itemized entry payloads carry no old id and totals are never undoable", () => {
    const entry = { ...TXN, id: "old-entry", parent_transaction_id: "tot" } as unknown as Transaction;
    const keys = Object.keys(itemizedEntryToInput(entry));
    for (const k of ["id", "property_id", "parent_transaction_id", "created_at", "updated_at"]) {
      expect(keys).not.toContain(k);
    }
    expect(isItemizedEntrySafeDelete(entry, 0)).toBe(true);
    expect(isItemizedEntrySafeDelete(entry, 1)).toBe(false);
    expect(isItemizedEntrySafeDelete(entry, null)).toBe(false);
    const total = { ...TXN, itemized: true } as unknown as Transaction;
    expect(isTransactionSafeDelete(total, 0)).toBe(false);
  });
});
