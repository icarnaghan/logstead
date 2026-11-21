import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "./ToastProvider";
import { useUndoableDelete } from "./useUndoableDelete";
import { isLoanSafeDelete, isTransactionSafeDelete } from "../../../lib/undoMappers";
import type { Loan } from "../../../api/loans";
import type { Transaction } from "../../../api/transactions";

// Source scan on purpose: these check which delete flow each caller wires up
// (useUndoableDelete vs ConfirmDialog vs window.confirm). Rendering each page
// and component would need per-page API fixtures for a wiring-only assertion.
import assetsPageSrc from "../../../pages/AssetsPage.tsx?raw";
import transactionsPageSrc from "../../../pages/TransactionsPage.tsx?raw";
import loansPageSrc from "../../../pages/LoansPage.tsx?raw";
import propertyListSrc from "../../properties/PropertyList.tsx?raw";
import deleteBusinessSrc from "../../businesses/DeleteBusinessConfirm.tsx?raw";
import businessDocumentsSrc from "../../businesses/BusinessDocuments.tsx?raw";
import propertyPhotosSrc from "../../photos/PropertyPhotos.tsx?raw";
import receiptListSrc from "../../transactions/ReceiptList.tsx?raw";

/**
 * Tests for `useUndoableDelete` and the per-delete Safe_Delete classification
 * (task 23.8, Requirements 13.1-13.8).
 */


afterEach(() => {
  vi.useRealTimers();
});

interface Item {
  id: number;
}
const ITEM: Item = { id: 7 };

function setup(overrides: {
  remove?: () => Promise<void>;
  restore?: () => Promise<unknown>;
}) {
  const remove = vi.fn(overrides.remove ?? (async () => {}));
  const restore = vi.fn(overrides.restore ?? (async () => ({})));
  const refresh = vi.fn(async () => {});

  function Harness() {
    const run = useUndoableDelete<Item>({
      remove,
      restore,
      refresh,
      deletedTitle: (i) => `Deleted ${i.id}`,
      restoredTitle: "Restored it",
      restoreFailedTitle: "Restore failed",
      deleteFailedTitle: "Delete failed",
    });
    return (
      <button type="button" onClick={() => void run(ITEM)}>
        Go
      </button>
    );
  }

  render(
    <ToastProvider>
      <Harness />
    </ToastProvider>,
  );
  return { remove, restore, refresh };
}

describe("useUndoableDelete (Req 13.2-13.6)", () => {
  it("shows an Undo toast and refreshes after a successful delete", async () => {
    const { remove, refresh } = setup({});
    fireEvent.click(screen.getByRole("button", { name: "Go" }));

    expect(await screen.findByText("Deleted 7")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
    expect(remove).toHaveBeenCalledWith(ITEM);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("Undo restores, refreshes, and shows a restored toast", async () => {
    const { restore, refresh } = setup({});
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    await screen.findByText("Deleted 7");

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));

    expect(await screen.findByText("Restored it")).toBeInTheDocument();
    expect(restore).toHaveBeenCalledWith(ITEM);
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("a failed restore shows an error toast and still refreshes", async () => {
    const { refresh } = setup({
      restore: async () => {
        throw new Error("nope");
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    await screen.findByText("Deleted 7");

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));

    expect(await screen.findByText("Restore failed")).toBeInTheDocument();
    expect(screen.queryByText("Restored it")).not.toBeInTheDocument();
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(2));
  });

  it("a failed remove shows an error toast with no Undo and no refresh", async () => {
    const { refresh, restore } = setup({
      remove: async () => {
        throw new Error("nope");
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Go" }));

    expect(await screen.findByText("Delete failed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
    expect(restore).not.toHaveBeenCalled();
  });

  it("the Undo toast stays at least 8s", async () => {
    vi.useFakeTimers();
    setup({});
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText("Deleted 7")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(8000);
    });
    expect(screen.getByText("Deleted 7")).toBeInTheDocument();
  });

  it("the Undo toast pauses while hovered", async () => {
    vi.useFakeTimers();
    setup({});
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const item = screen.getByText("Deleted 7").closest("li") as HTMLElement;

    fireEvent.pointerMove(item);
    act(() => {
      vi.advanceTimersByTime(30000);
    });
    expect(screen.getByText("Deleted 7")).toBeInTheDocument();
  });

  it("the Undo toast pauses while focus is inside it", async () => {
    vi.useFakeTimers();
    setup({});
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const undo = screen.getByRole("button", { name: "Undo" });

    act(() => {
      undo.focus();
    });
    act(() => {
      vi.advanceTimersByTime(30000);
    });
    expect(screen.getByText("Deleted 7")).toBeInTheDocument();
  });
});

describe("delete classification (Req 13.1, 13.7, 13.8)", () => {
  const tx = (imported: boolean) => ({ id: 1, imported }) as unknown as Transaction;
  const loan = (overrides: Record<string, unknown>) =>
    ({ id: 1, interest_overrides: overrides }) as unknown as Loan;

  it("transactions are safe only when not imported and with zero receipts", () => {
    expect(isTransactionSafeDelete(tx(false), 0)).toBe(true);
    expect(isTransactionSafeDelete(tx(true), 0)).toBe(false);
    expect(isTransactionSafeDelete(tx(false), 2)).toBe(false);
    // listReceipts failure is treated as unknown, never safe.
    expect(isTransactionSafeDelete(tx(false), null)).toBe(false);
  });

  it("loans are safe only without interest overrides", () => {
    expect(isLoanSafeDelete(loan({}))).toBe(true);
    expect(isLoanSafeDelete(loan({ "2024-01": 5 }))).toBe(false);
  });

  it("assets always use useUndoableDelete with no ConfirmDialog", () => {
    expect(assetsPageSrc).toMatch(/useUndoableDelete</);
    expect(assetsPageSrc).not.toMatch(/ConfirmDialog/);
  });

  it("transactions and loans gate Undo on the classifiers and keep ConfirmDialog", () => {
    expect(transactionsPageSrc).toMatch(/useUndoableDelete</);
    expect(transactionsPageSrc).toMatch(/isTransactionSafeDelete\(/);
    expect(transactionsPageSrc).toMatch(/<ConfirmDialog/);
    expect(loansPageSrc).toMatch(/useUndoableDelete</);
    expect(loansPageSrc).toMatch(/isLoanSafeDelete\(/);
    expect(loansPageSrc).toMatch(/<ConfirmDialog/);
  });

  it("property, business, document, photo, and receipt deletes keep confirm flows without Undo", () => {
    for (const src of [
      propertyListSrc,
      deleteBusinessSrc,
      businessDocumentsSrc,
      propertyPhotosSrc,
      receiptListSrc,
    ]) {
      expect(src).not.toMatch(/useUndoableDelete/);
    }
    expect(propertyListSrc).toMatch(/<ConfirmDialog/);
    expect(deleteBusinessSrc).toMatch(/<ConfirmDialog/);
    expect(receiptListSrc).toMatch(/<ConfirmDialog/);
    expect(businessDocumentsSrc).toMatch(/window\.confirm/);
    expect(propertyPhotosSrc).toMatch(/window\.confirm/);
  });
});
