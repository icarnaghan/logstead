import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import TransactionsPage from "./TransactionsPage";
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
  {
    id: "other",
    kind: "expense",
    label: "Other",
    schedule_e_line: "19",
    requires_description: true,
  },
];

const RENT: Transaction = {
  id: "t-rent",
  property_id: "p1",
  date: "2024-06-15",
  amount: "1500.00",
  type: "income",
  category_id: "rents",
  description: null,
};
const SINK: Transaction = {
  id: "t-sink",
  property_id: "p1",
  date: "2024-03-05",
  amount: "250.00",
  type: "expense",
  category_id: "repairs",
  description: "Fix sink",
};
const GARDEN: Transaction = {
  id: "t-garden",
  property_id: "p1",
  date: "2024-01-09",
  amount: "99.50",
  type: "expense",
  category_id: "rents",
  description: "Garden",
};

function makeApi(rows: Transaction[] = [RENT, SINK, GARDEN]) {
  return {
    listCategories: vi.fn().mockResolvedValue(CATEGORIES),
    listTransactions: vi.fn().mockResolvedValue(rows),
    createTransaction: vi.fn(),
    getTransaction: vi.fn(),
    updateTransaction: vi.fn(),
    deleteTransaction: vi.fn(),
    attachReceipt: vi.fn(),
    uploadToPresignedUrl: vi.fn(),
    listReceipts: vi.fn().mockResolvedValue([] as ReceiptDocument[]),
    deleteReceipt: vi.fn(),
  } as unknown as TransactionsApi;
}

async function renderPage(api: TransactionsApi) {
  const view = render(
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
  await screen.findByRole("table");
  return view;
}

const search = () => screen.getByRole("searchbox", { name: "Search transactions" });
const categorySelect = () =>
  screen.getByLabelText("Category") as HTMLSelectElement;
const inTable = (text: string) =>
  within(screen.getByRole("table")).getByText(text);
const dataRows = () => screen.getAllByRole("row").slice(1);

describe("TransactionsPage — search and filters (Req 21)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("exposes a labelled search input and shows all rows with no count when empty", async () => {
    await renderPage(makeApi());
    expect(search()).toBeInTheDocument();
    expect(dataRows()).toHaveLength(3);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("filters by description, category label, and amount text", async () => {
    const user = userEvent.setup();
    await renderPage(makeApi());

    await user.type(search(), "sink");
    expect(dataRows()).toHaveLength(1);
    expect(inTable("2024-03-05")).toBeInTheDocument();

    await user.clear(search());
    await user.type(search(), "repairs");
    expect(dataRows()).toHaveLength(1);
    expect(inTable("2024-03-05")).toBeInTheDocument();

    await user.clear(search());
    await user.type(search(), "1,500");
    expect(dataRows()).toHaveLength(1);
    expect(inTable("2024-06-15")).toBeInTheDocument();

    await user.clear(search());
    await user.type(search(), "99.50");
    expect(dataRows()).toHaveLength(1);
    expect(inTable("2024-01-09")).toBeInTheDocument();

    await user.clear(search());
    expect(dataRows()).toHaveLength(3);
  });

  it("lists only categories present in the loaded transactions", async () => {
    await renderPage(makeApi());
    const labels = Array.from(categorySelect().options).map((o) => o.text);
    expect(labels).toEqual(["All categories", "Rents received", "Repairs"]);
  });

  it("filters by category and composes with the search query", async () => {
    const user = userEvent.setup();
    await renderPage(makeApi());

    await user.selectOptions(categorySelect(), "rents");
    expect(dataRows()).toHaveLength(2);

    await user.type(search(), "garden");
    expect(dataRows()).toHaveLength(1);
    expect(inTable("2024-01-09")).toBeInTheDocument();
  });

  it("shows the count in a polite status region only while a filter is active", async () => {
    const user = userEvent.setup();
    await renderPage(makeApi());

    await user.type(search(), "sink");
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveTextContent("Showing 1 of 3 transactions");

    await user.clear(search());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    await user.selectOptions(categorySelect(), "rents");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Showing 2 of 3 transactions",
    );
  });

  it("shows a no-match empty state and Clear filters resets both filters", async () => {
    const user = userEvent.setup();
    await renderPage(makeApi());

    await user.selectOptions(categorySelect(), "repairs");
    await user.type(search(), "zzz");
    expect(
      screen.getByText("No transactions match your filters"),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Showing 0 of 3 transactions",
    );

    await user.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(search()).toHaveValue("");
    expect(categorySelect().value).toBe("all");
    expect(dataRows()).toHaveLength(3);
    expect(
      screen.queryByText("No transactions match your filters"),
    ).not.toBeInTheDocument();
  });

  it("makes no extra API calls when filtering", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    await renderPage(api);
    const listMock = api.listTransactions as ReturnType<typeof vi.fn>;
    const categoriesMock = api.listCategories as ReturnType<typeof vi.fn>;
    const listCalls = listMock.mock.calls.length;
    const categoryCalls = categoriesMock.mock.calls.length;

    await user.type(search(), "sink");
    await user.selectOptions(categorySelect(), "repairs");
    await user.clear(search());

    expect(listMock).toHaveBeenCalledTimes(listCalls);
    expect(categoriesMock).toHaveBeenCalledTimes(categoryCalls);
  });

  it("keeps filters when the list refreshes", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    await renderPage(api);
    const listMock = api.listTransactions as ReturnType<typeof vi.fn>;
    const before = listMock.mock.calls.length;

    await user.type(search(), "sink");
    await user.selectOptions(screen.getByLabelText(/tax year/i), "all");
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(before + 1));

    await waitFor(() => expect(dataRows()).toHaveLength(1));
    expect(search()).toHaveValue("sink");
  });

  it("drops a category selection that left the list after a year change", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    await renderPage(api);

    await user.selectOptions(categorySelect(), "repairs");
    expect(dataRows()).toHaveLength(1);

    // The other year only has rent rows, so "repairs" is no longer present.
    (api.listTransactions as ReturnType<typeof vi.fn>).mockResolvedValue([
      RENT,
      GARDEN,
    ]);
    await user.selectOptions(screen.getByLabelText(/tax year/i), "all");

    await waitFor(() => expect(dataRows()).toHaveLength(2));
    expect(categorySelect().value).toBe("all");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("has no axe violations with an active filter", async () => {
    const user = userEvent.setup();
    const { container } = await renderPage(makeApi());
    await user.type(search(), "sink");

    const results = await axe(container, {
      // jsdom cannot compute colors; contrast stays a manual-AT check.
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });

  it("has no axe violations in the no-match state", async () => {
    const user = userEvent.setup();
    const { container } = await renderPage(makeApi());
    await user.type(search(), "zzz");

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
