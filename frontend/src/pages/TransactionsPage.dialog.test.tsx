import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import TransactionsPage from "./TransactionsPage";
import { ApiError } from "../lib/apiClient";
import { ToastProvider } from "../components/ui";
import type {
  Category,
  ReceiptDocument,
  Transaction,
  TransactionsApi,
} from "../api/transactions";

// Same stubs as TransactionsPage.test.tsx: no network in jsdom.
vi.mock("../api/properties", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/properties")>()),
  getEarliestDataYear: vi.fn().mockResolvedValue(null),
}));

vi.mock("../api/assets", () => ({
  listAssets: vi.fn().mockResolvedValue([]),
}));

const CATEGORIES: Category[] = [
  {
    id: "rents",
    kind: "income",
    label: "Rents received",
    schedule_e_line: "3",
    requires_description: false,
  },
  {
    id: "repairs",
    kind: "expense",
    label: "Repairs",
    schedule_e_line: "14",
    requires_description: false,
  },
];

const TX: Transaction = {
  id: "t1",
  property_id: "p1",
  date: "2024-06-15",
  amount: "1500.00",
  type: "income",
  category_id: "rents",
  description: null,
};

function makeApi(overrides: Partial<TransactionsApi> = {}) {
  return {
    listCategories: vi.fn().mockResolvedValue(CATEGORIES),
    listTransactions: vi.fn().mockResolvedValue([TX]),
    createTransaction: vi.fn().mockResolvedValue(TX),
    getTransaction: vi.fn(),
    updateTransaction: vi.fn().mockResolvedValue(TX),
    deleteTransaction: vi.fn().mockResolvedValue(undefined),
    attachReceipt: vi.fn(),
    uploadToPresignedUrl: vi.fn().mockResolvedValue(undefined),
    listReceipts: vi.fn().mockResolvedValue([] as ReceiptDocument[]),
    deleteReceipt: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  } as unknown as TransactionsApi;
}

function renderPage(api: TransactionsApi) {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/properties/p1/transactions"]}>
        <Routes>
          <Route
            path="/properties/:propertyId/transactions"
            element={<TransactionsPage api={api} />}
          />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

/** Render, wait for the list, and open the add dialog from the toolbar. */
async function openAdd(
  user: ReturnType<typeof userEvent.setup>,
  api: TransactionsApi,
) {
  renderPage(api);
  await screen.findAllByRole("row");
  const opener = screen.getByRole("button", { name: "Add transaction" });
  await user.click(opener);
  const dialog = await screen.findByRole("dialog", { name: "Add transaction" });
  return { opener, dialog };
}

async function fillValid(dialog: HTMLElement, user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(within(dialog).getByLabelText(/category/i), "repairs");
  await user.type(within(dialog).getByLabelText(/amount/i), "40");
}

describe("TransactionsPage dialog (Req 9.1, 9.2, 9.6-9.9, 10.2)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("opens as a dialog with no second close button (Req 9.1, 9.2)", async () => {
    const user = userEvent.setup();
    const { dialog } = await openAdd(user, makeApi());

    // The only dismiss control is the form's Cancel button; no hand-built (x).
    expect(
      within(dialog).queryByRole("button", { name: /^(close|×|x)$/i }),
    ).not.toBeInTheDocument();
    expect(within(dialog).getAllByRole("button").map((b) => b.textContent)).toEqual(
      ["Cancel", "Add transaction"],
    );
  });

  it("moves focus to the first field on open (Req 9.9)", async () => {
    const user = userEvent.setup();
    const { dialog } = await openAdd(user, makeApi());

    await waitFor(() => expect(dialog).toContainElement(document.activeElement as HTMLElement));
    const form = dialog.querySelector("form") as HTMLFormElement;
    const firstField = form.querySelector<HTMLElement>("input, select, textarea");
    expect(document.activeElement).toBe(firstField);
  });

  it("closes and refreshes the list on success (Req 9.6)", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    const { dialog } = await openAdd(user, api);
    const listMock = api.listTransactions as ReturnType<typeof vi.fn>;
    const callsBefore = listMock.mock.calls.length;

    await fillValid(dialog, user);
    await user.click(within(dialog).getByRole("button", { name: "Add transaction" }));

    await waitFor(() => expect(api.createTransaction).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(listMock.mock.calls.length).toBeGreaterThan(callsBefore);
    expect(screen.queryByText("Discard changes?")).not.toBeInTheDocument();
  });

  it("stays open with values retained and an error shown on failure (Req 9.7)", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      createTransaction: vi
        .fn()
        .mockRejectedValue(new ApiError(500, "boom", undefined)),
    });
    const { dialog } = await openAdd(user, api);

    await fillValid(dialog, user);
    await user.type(within(dialog).getByLabelText(/description/i), "Fix sink");
    await user.click(within(dialog).getByRole("button", { name: "Add transaction" }));

    expect(
      (await within(dialog).findAllByText(/could not save the transaction/i))[0],
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Add transaction" })).toBe(dialog);
    expect(within(dialog).getByLabelText(/amount/i)).toHaveDisplayValue(/^40(\.00)?$/);
    expect(within(dialog).getByLabelText(/category/i)).toHaveValue("repairs");
    expect(within(dialog).getByLabelText(/description/i)).toHaveValue("Fix sink");
  });

  describe.each([
    [
      "Escape",
      async (user: ReturnType<typeof userEvent.setup>) => {
        await user.keyboard("{Escape}");
      },
    ],
    [
      "backdrop",
      async () => {
        await new Promise((r) => setTimeout(r, 0));
        fireEvent.pointerDown(document.body);
      },
    ],
    [
      "Cancel",
      async (user: ReturnType<typeof userEvent.setup>) => {
        await user.click(
          within(screen.getByRole("dialog", { name: "Add transaction" })).getByRole(
            "button",
            { name: "Cancel" },
          ),
        );
      },
    ],
  ])("closing a dirty form via %s (Req 10.2)", (_name, close) => {
    it("shows the discard confirmation and keeps the edit", async () => {
      const user = userEvent.setup();
      const { dialog } = await openAdd(user, makeApi());
      await user.type(within(dialog).getByLabelText(/amount/i), "12");

      await close(user);

      expect(
        await screen.findByRole("dialog", { name: "Discard changes?" }),
      ).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Keep editing" }));
      expect(
        screen.queryByRole("dialog", { name: "Discard changes?" }),
      ).not.toBeInTheDocument();
      expect(screen.getByLabelText(/amount/i)).toHaveDisplayValue(/^12(\.00)?$/);
    });
  });

  it("closes a clean form without the confirmation and returns focus to the opener (Req 9.9)", async () => {
    const user = userEvent.setup();
    const { opener, dialog } = await openAdd(user, makeApi());

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(screen.queryByText("Discard changes?")).not.toBeInTheDocument();
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it("discarding closes the dialog and returns focus to the opener (Req 9.9, 10.2)", async () => {
    const user = userEvent.setup();
    const { opener, dialog } = await openAdd(user, makeApi());
    await user.type(within(dialog).getByLabelText(/amount/i), "12");

    await user.keyboard("{Escape}");
    await user.click(await screen.findByRole("button", { name: "Discard" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it("has no axe violations on the open dialog", async () => {
    const user = userEvent.setup();
    const { dialog } = await openAdd(user, makeApi());

    const results = await axe(dialog, {
      // jsdom cannot compute colors; contrast stays a manual-AT check.
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
