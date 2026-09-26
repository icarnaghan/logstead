import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi, beforeEach } from "vitest";
import TransactionsPage from "./TransactionsPage";
import { ApiError } from "../lib/apiClient";
import { ToastProvider } from "../components/ui";
import type {
  Category,
  ReceiptDocument,
  Transaction,
  TransactionsApi,
} from "../api/transactions";

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
  {
    id: "other",
    kind: "expense",
    label: "Other",
    schedule_e_line: "19",
    requires_description: true,
  },
];

// Two transactions returned out of order so we can assert the UI shows the
// order the API returns (the API sorts date-descending — Requirement 5.4).
const TX_NEWER: Transaction = {
  id: "t-newer",
  property_id: "p1",
  date: "2024-06-15",
  amount: "1500.00",
  type: "income",
  category_id: "rents",
  description: null,
};
const TX_OLDER: Transaction = {
  id: "t-older",
  property_id: "p1",
  date: "2024-01-05",
  amount: "250.00",
  type: "expense",
  category_id: "repairs",
  description: "Fix sink",
};

/** Build a fully-stubbed TransactionsApi with sensible defaults. */
function makeApi(overrides: Partial<TransactionsApi> = {}) {
  const api = {
    listCategories: vi.fn().mockResolvedValue(CATEGORIES),
    listTransactions: vi.fn().mockResolvedValue([TX_NEWER, TX_OLDER]),
    createTransaction: vi.fn().mockResolvedValue(TX_NEWER),
    getTransaction: vi.fn(),
    updateTransaction: vi.fn().mockResolvedValue(TX_NEWER),
    deleteTransaction: vi.fn().mockResolvedValue(undefined),
    attachReceipt: vi.fn(),
    uploadToPresignedUrl: vi.fn().mockResolvedValue(undefined),
    listReceipts: vi.fn().mockResolvedValue([] as ReceiptDocument[]),
    deleteReceipt: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  return api as unknown as TransactionsApi;
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

describe("TransactionsPage — list (Req 5.4)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders transactions in the order the API returns (newest first)", async () => {
    const api = makeApi();
    renderPage(api);

    const rows = await screen.findAllByRole("row");
    // rows[0] is the header row; first data row is the newer transaction.
    const firstData = rows[1];
    expect(within(firstData).getByText("2024-06-15")).toBeInTheDocument();
    const secondData = rows[2];
    expect(within(secondData).getByText("2024-01-05")).toBeInTheDocument();
  });
});

describe("TransactionsPage — empty/loading states (Req 9.1, 9.2, 9.3)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a role=status loading state while transactions are fetching", async () => {
    let resolve: (rows: Transaction[]) => void = () => {};
    const api = makeApi({
      listTransactions: vi.fn().mockImplementation(
        () =>
          new Promise<Transaction[]>((r) => {
            resolve = r;
          }),
      ),
    });
    renderPage(api);

    expect(await screen.findByRole("status")).toHaveTextContent(
      /loading transactions/i,
    );

    // Let the fetch settle so the test exits cleanly.
    resolve([]);
    await screen.findByRole("heading", { name: /no transactions yet/i });
  });

  it("renders an empty state with a next action when there are none", async () => {
    const api = makeApi({
      listTransactions: vi.fn().mockResolvedValue([] as Transaction[]),
    });
    renderPage(api);

    expect(
      await screen.findByRole("heading", { name: /no transactions yet/i }),
    ).toBeInTheDocument();
    // The empty state offers the add-transaction action (Req 9.2/9.3).
    expect(
      screen.getAllByRole("button", { name: /add transaction/i }).length,
    ).toBeGreaterThan(0);
  });
});

describe("TransactionsPage — create (Req 5.1, 7.3)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("posts the right body when adding an expense", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);
    await screen.findAllByRole("row");

    await user.click(screen.getByRole("button", { name: /add transaction/i }));

    const dialog = await screen.findByRole("dialog");
    // type defaults to expense; pick the Repairs category.
    await user.selectOptions(
      within(dialog).getByLabelText(/category/i),
      "repairs",
    );
    await user.clear(within(dialog).getByLabelText(/amount/i));
    await user.type(within(dialog).getByLabelText(/amount/i), "99.5");
    // Date defaults to today (a valid value), so no need to type one.

    await user.click(
      within(dialog).getByRole("button", { name: /add transaction/i }),
    );

    await waitFor(() =>
      expect(api.createTransaction).toHaveBeenCalledTimes(1),
    );
    const [propertyId, input] = (api.createTransaction as ReturnType<typeof vi.fn>)
      .mock.calls[0];
    expect(propertyId).toBe("p1");
    expect(input).toMatchObject({
      amount: "99.50",
      type: "expense",
      category_id: "repairs",
    });

    // A success toast confirms the outcome (Req 5.1).
    expect(await screen.findByText(/transaction added/i)).toBeInTheDocument();
  });

  it("shows the Schedule E line for the selected category (Req 7.3)", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);
    await screen.findAllByRole("row");

    await user.click(screen.getByRole("button", { name: /add transaction/i }));
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(
      within(dialog).getByLabelText(/category/i),
      "repairs",
    );
    expect(within(dialog).getByText(/Schedule E Line 14/i)).toBeInTheDocument();
  });
});

describe("TransactionsPage — Other requires description (Req 7.4)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("blocks submit and shows a field error when Other has no description", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);
    await screen.findAllByRole("row");

    await user.click(screen.getByRole("button", { name: /add transaction/i }));
    const dialog = await screen.findByRole("dialog");

    await user.selectOptions(within(dialog).getByLabelText(/category/i), "other");
    await user.type(within(dialog).getByLabelText(/amount/i), "40.00");

    await user.click(
      within(dialog).getByRole("button", { name: /add transaction/i }),
    );

    expect(api.createTransaction).not.toHaveBeenCalled();
    expect(
      within(dialog).getByText(/description is required for the other category/i),
    ).toBeInTheDocument();
  });

  it("surfaces a server 400 field error next to the description", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      createTransaction: vi
        .fn()
        .mockRejectedValue(
          new ApiError(400, "bad", {
            field: "description",
            message: "Description must not be blank.",
          }),
        ),
    });
    renderPage(api);
    await screen.findAllByRole("row");

    await user.click(screen.getByRole("button", { name: /add transaction/i }));
    const dialog = await screen.findByRole("dialog");
    // Provide a client-valid description so submit reaches the server, which
    // then rejects it.
    await user.selectOptions(within(dialog).getByLabelText(/category/i), "other");
    await user.type(within(dialog).getByLabelText(/amount/i), "40.00");
    await user.type(within(dialog).getByLabelText(/description/i), "misc");

    await user.click(
      within(dialog).getByRole("button", { name: /add transaction/i }),
    );

    expect(
      await within(dialog).findByText(/description must not be blank/i),
    ).toBeInTheDocument();
  });
});

describe("TransactionsPage — tax-year filter (Req 5.5)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("re-queries with the selected tax year", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);
    await screen.findAllByRole("row");

    const listMock = api.listTransactions as ReturnType<typeof vi.fn>;
    // Initial load: all years (undefined tax year).
    expect(listMock).toHaveBeenCalledWith("p1", undefined, expect.anything());

    const year = new Date().getFullYear();
    await user.selectOptions(
      screen.getByLabelText(/tax year/i),
      String(year),
    );

    await waitFor(() =>
      expect(listMock).toHaveBeenCalledWith("p1", year, expect.anything()),
    );
  });
});

describe("TransactionsPage — receipts (Req 5.8)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("requests a pre-signed URL then PUTs the file", async () => {
    const user = userEvent.setup();
    const attachReceipt = vi.fn().mockResolvedValue({
      upload_url: "https://s3.example.com/put",
      document: { id: "d1", filename: "r.pdf", content_type: "application/pdf" },
    });
    const uploadToPresignedUrl = vi.fn().mockResolvedValue(undefined);
    const api = makeApi({ attachReceipt, uploadToPresignedUrl });
    renderPage(api);
    await screen.findAllByRole("row");

    // Expand the documents panel for the first data row.
    const receiptsButtons = screen.getAllByRole("button", { name: /^documents$/i });
    await user.click(receiptsButtons[0]);

    const fileInput = await screen.findByLabelText(/attach a document/i);
    const file = new File(["bytes"], "r.pdf", { type: "application/pdf" });
    await user.upload(fileInput as HTMLInputElement, file);

    await waitFor(() => expect(attachReceipt).toHaveBeenCalledTimes(1));
    expect(uploadToPresignedUrl).toHaveBeenCalledWith(
      "https://s3.example.com/put",
      file,
      "application/pdf",
    );
  });
});

describe("TransactionsPage — delete (Req 4, 5.1, 5.7)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("confirms before deleting, then calls deleteTransaction and toasts success", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);
    await screen.findAllByRole("row");

    const deleteButtons = screen.getAllByRole("button", {
      name: /delete transaction from/i,
    });
    await user.click(deleteButtons[0]);

    // A confirmation dialog appears; nothing is deleted yet.
    const dialog = await screen.findByRole("dialog");
    expect(api.deleteTransaction).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    await waitFor(() =>
      expect(api.deleteTransaction).toHaveBeenCalledWith("p1", "t-newer"),
    );
    expect(await screen.findByText(/transaction deleted/i)).toBeInTheDocument();
  });

  it("does not delete when the confirmation is cancelled", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);
    await screen.findAllByRole("row");

    const deleteButtons = screen.getAllByRole("button", {
      name: /delete transaction from/i,
    });
    await user.click(deleteButtons[0]);

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));

    expect(api.deleteTransaction).not.toHaveBeenCalled();
  });
});
