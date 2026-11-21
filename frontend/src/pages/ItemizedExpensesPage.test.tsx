import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ItemizedExpensesPage from "./ItemizedExpensesPage";
import { ToastProvider } from "../components/ui";
import { ApiError } from "../lib/apiClient";
import { ITEMIZED_PAGES, type ItemizedPageDefinition } from "../lib/itemizedPages";
import type { ItemizedApi, ItemizedSummary } from "../api/itemized";
import type {
  ReceiptDocument,
  Transaction,
  TransactionsApi,
} from "../api/transactions";

// Same stubs as TransactionsPage.test.tsx: the year range loads the earliest
// data year, which must not hit the network in jsdom.
vi.mock("../api/properties", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/properties")>()),
  getEarliestDataYear: vi.fn().mockResolvedValue(null),
}));

const COMPLETED_YEAR = new Date().getFullYear() - 1;
const CURRENT_YEAR = new Date().getFullYear();

function entry(id: string, over: Partial<Transaction> = {}): Transaction {
  return {
    id,
    property_id: "p1",
    date: `${COMPLETED_YEAR}-03-10`,
    amount: "620.00",
    type: "expense",
    category_id: "repairs",
    description: "Plumber",
    itemized: true,
    ...over,
  };
}

function totalRow(id: string, amount: string, over: Partial<Transaction> = {}) {
  return entry(id, {
    date: `${COMPLETED_YEAR}-12-31`,
    amount,
    description: null,
    itemized: false,
    ...over,
  });
}

/** Build a consistent summary (the page requires `tax_year` to match). */
function summaryOf(
  year: number,
  over: Partial<ItemizedSummary> = {},
): ItemizedSummary {
  return {
    category_id: "repairs",
    label: "Repairs",
    schedule_e_line: 14,
    tax_year: year,
    entered_total: null,
    entered_total_rows: [],
    itemized_sum: "0.00",
    itemized_count: 0,
    entries: [],
    remainder: null,
    line_total: "0.00",
    line_source: "none",
    total_differs_from_itemized: false,
    ...over,
  };
}

/** Total 4200.00 with one 3100.00 entry: sync is offered. */
function bothSummary(year: number, over: Partial<ItemizedSummary> = {}) {
  const e1 = entry("e1", { amount: "3100.00", description: "Roof patch" });
  return summaryOf(year, {
    entered_total: "4200.00",
    entered_total_rows: [totalRow("tot", "4200.00")],
    itemized_sum: "3100.00",
    itemized_count: 1,
    entries: [e1],
    remainder: "1100.00",
    line_total: "4200.00",
    line_source: "entered_total",
    total_differs_from_itemized: true,
    ...over,
  });
}

type SummaryFactory = (year: number) => ItemizedSummary;

function makeApi(
  factory: SummaryFactory = (year) => summaryOf(year),
  overrides: Partial<ItemizedApi> = {},
) {
  const api = {
    getSummary: vi
      .fn()
      .mockImplementation((_p: string, _c: string, year: number) =>
        Promise.resolve(factory(year)),
      ),
    createEntry: vi.fn().mockResolvedValue(entry("new")),
    updateEntry: vi.fn().mockResolvedValue(entry("e1")),
    deleteEntry: vi.fn().mockResolvedValue(undefined),
    setTotal: vi.fn().mockResolvedValue(summaryOf(COMPLETED_YEAR)),
    removeTotal: vi.fn().mockResolvedValue(summaryOf(COMPLETED_YEAR)),
    ...overrides,
  };
  return api as unknown as ItemizedApi & {
    getSummary: ReturnType<typeof vi.fn>;
    createEntry: ReturnType<typeof vi.fn>;
    deleteEntry: ReturnType<typeof vi.fn>;
    setTotal: ReturnType<typeof vi.fn>;
    removeTotal: ReturnType<typeof vi.fn>;
  };
}

function makeReceiptsApi(overrides: Partial<TransactionsApi> = {}) {
  return {
    listReceipts: vi.fn().mockResolvedValue([] as ReceiptDocument[]),
    attachReceipt: vi.fn(),
    uploadToPresignedUrl: vi.fn(),
    deleteReceipt: vi.fn(),
    ...overrides,
  } as unknown as TransactionsApi;
}

function renderPage(
  api: ItemizedApi,
  {
    receiptsApi = makeReceiptsApi(),
    url = "/properties/p1/repairs",
    definition = ITEMIZED_PAGES.repairs as ItemizedPageDefinition,
  }: {
    receiptsApi?: TransactionsApi;
    url?: string;
    definition?: ItemizedPageDefinition;
  } = {},
) {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route
            path="/properties/:propertyId/repairs"
            element={
              <ItemizedExpensesPage
                definition={definition}
                api={api}
                receiptsApi={receiptsApi}
              />
            }
          />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

function summaryValue(term: string): string {
  const dt = screen.getByText(term, { selector: "dt" });
  return dt.parentElement?.textContent ?? "";
}

describe("ItemizedExpensesPage: states (Req 1.4, 1.5, 7.1)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a loading status while the summary is fetching", async () => {
    let resolve: (s: ItemizedSummary) => void = () => {};
    const api = makeApi(undefined, {
      getSummary: vi.fn().mockImplementation(
        () => new Promise<ItemizedSummary>((r) => (resolve = r)),
      ),
    } as Partial<ItemizedApi>);
    renderPage(api);

    expect(await screen.findByRole("status")).toHaveAccessibleName(
      /loading repairs/i,
    );
    resolve(summaryOf(COMPLETED_YEAR));
    await screen.findByText(/no total entered/i, { selector: "dd" });
  });

  it("shows a retryable error and recovers on Retry", async () => {
    const user = userEvent.setup();
    const getSummary = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValue(summaryOf(COMPLETED_YEAR));
    renderPage(makeApi(undefined, { getSummary } as Partial<ItemizedApi>));

    const alert = await screen.findByRole("alert");
    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("Summary for " + COMPLETED_YEAR)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(getSummary).toHaveBeenCalledTimes(2);
  });

  it("renders the empty state with Set total and Add repair available", async () => {
    renderPage(makeApi());

    expect(
      await screen.findByText(/no repairs yet/i),
    ).toBeInTheDocument();
    expect(summaryValue("Entered total")).toMatch(/no total entered/i);
    expect(summaryValue("Line 14 total")).toContain("$0.00");
    expect(
      screen.getByText("Line 14 has no amount for this year"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set total" })).toBeEnabled();
    expect(screen.getAllByRole("button", { name: /add repair/i })[0]).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: /update total to/i }),
    ).not.toBeInTheDocument();
  });

  it("defaults to the latest completed tax year", async () => {
    const api = makeApi();
    renderPage(api);
    await screen.findByText(/no repairs yet/i);
    expect(api.getSummary).toHaveBeenCalledWith(
      "p1",
      "repairs",
      COMPLETED_YEAR,
      expect.anything(),
    );
    expect((screen.getByLabelText(/tax year/i) as HTMLSelectElement).value).toBe(
      String(COMPLETED_YEAR),
    );
  });
});

describe("ItemizedExpensesPage: summary combinations (Req 7.1, 7.4, 7.5)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("total only: line uses the entered total, no sync", async () => {
    renderPage(
      makeApi((y) =>
        summaryOf(y, {
          entered_total: "4200.00",
          entered_total_rows: [totalRow("tot", "4200.00")],
          remainder: "4200.00",
          line_total: "4200.00",
          line_source: "entered_total",
        }),
      ),
    );
    await screen.findByText("Line 14 uses: entered total");
    expect(summaryValue("Entered total")).toContain("$4,200.00");
    expect(summaryValue("Itemized sum")).toContain("$0.00");
    expect(summaryValue("Itemized sum")).toContain("0 entries");
    expect(summaryValue("Unitemized remainder")).toContain("$4,200.00");
    expect(
      screen.queryByRole("button", { name: /update total to/i }),
    ).not.toBeInTheDocument();
  });

  it("itemized only: line uses the itemized entries, no remainder row", async () => {
    renderPage(
      makeApi((y) =>
        summaryOf(y, {
          itemized_sum: "620.00",
          itemized_count: 1,
          entries: [entry("e1", { notes: "Invoice 1182" })],
          line_total: "620.00",
          line_source: "itemized",
        }),
      ),
    );
    await screen.findByText("Line 14 uses: itemized entries");
    expect(summaryValue("Itemized sum")).toContain("1 entry");
    expect(screen.queryByText("Unitemized remainder")).not.toBeInTheDocument();
    expect(summaryValue("Line 14 total")).toContain("$620.00");
    expect(screen.getByText("Invoice 1182")).toBeInTheDocument();
    expect(summaryValue("Entered total")).toContain("No total entered");
  });

  it("both with a positive remainder shows no over-total flag", async () => {
    renderPage(makeApi((y) => bothSummary(y)));
    await screen.findByText("Line 14 uses: entered total");
    expect(summaryValue("Unitemized remainder")).toContain("$1,100.00");
    expect(screen.queryByText("Over total")).not.toBeInTheDocument();
  });

  it("both with a negative remainder flags it with text", async () => {
    renderPage(
      makeApi((y) =>
        bothSummary(y, {
          entered_total: "1000.00",
          entered_total_rows: [totalRow("tot", "1000.00")],
          remainder: "-2100.00",
          line_total: "1000.00",
        }),
      ),
    );
    await screen.findByText("Line 14 uses: entered total");
    expect(summaryValue("Unitemized remainder")).toContain("-$2,100.00");
    expect(screen.getByText("Over total")).toBeInTheDocument();
    expect(
      screen.getByText(/itemized entries exceed the entered total/i),
    ).toBeInTheDocument();
  });

  it("links to Assets for capital improvements (Req 1.7)", async () => {
    renderPage(makeApi());
    const link = await screen.findByRole("link", { name: "depreciable assets" });
    expect(link).toHaveAttribute("href", "/properties/p1/assets");
  });
});

describe("ItemizedExpensesPage: year search parameter (Req 1.8)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("honors ?year= on load and writes the new year on change", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api, { url: "/properties/p1/repairs?year=2021" });
    await screen.findByText(/no repairs yet/i);

    expect(api.getSummary).toHaveBeenCalledWith(
      "p1",
      "repairs",
      2021,
      expect.anything(),
    );
    const select = screen.getByLabelText(/tax year/i) as HTMLSelectElement;
    expect(select.value).toBe("2021");

    await user.selectOptions(select, String(COMPLETED_YEAR));
    await waitFor(() =>
      expect(api.getSummary).toHaveBeenCalledWith(
        "p1",
        "repairs",
        COMPLETED_YEAR,
        expect.anything(),
      ),
    );
  });

  it("ignores a malformed ?year= value", async () => {
    const api = makeApi();
    renderPage(api, { url: "/properties/p1/repairs?year=abc" });
    await screen.findByText(/no repairs yet/i);
    expect(api.getSummary).toHaveBeenCalledWith(
      "p1",
      "repairs",
      COMPLETED_YEAR,
      expect.anything(),
    );
  });
});

describe("ItemizedExpensesPage: sync (Req 9.4, 9.7, 9.8, 9.9)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the sync action with the itemized sum in the label", async () => {
    renderPage(makeApi((y) => bothSummary(y)));
    expect(
      await screen.findByRole("button", {
        name: "Update total to $3,100.00 (itemized)",
      }),
    ).toBeInTheDocument();
  });

  it("hides sync when the itemized sum equals the total", async () => {
    renderPage(
      makeApi((y) =>
        bothSummary(y, {
          entered_total: "3100.00",
          entered_total_rows: [totalRow("tot", "3100.00")],
          remainder: "0.00",
          total_differs_from_itemized: false,
        }),
      ),
    );
    await screen.findByText("Line 14 uses: entered total");
    expect(
      screen.queryByRole("button", { name: /update total to/i }),
    ).not.toBeInTheDocument();
  });

  it("dialog names the change and warns for a completed year", async () => {
    const user = userEvent.setup();
    renderPage(makeApi((y) => bothSummary(y)));
    await user.click(
      await screen.findByRole("button", { name: /update total to/i }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      `Schedule E line 14 for ${COMPLETED_YEAR} will change from $4,200.00 to $3,100.00 (-$1,100.00)`,
    );
    expect(dialog).toHaveTextContent(/completed tax year/i);
    expect(dialog).toHaveTextContent(/no longer match the filed return/i);
  });

  it("dialog has no filed-return warning for the current year", async () => {
    const user = userEvent.setup();
    renderPage(makeApi((y) => bothSummary(y)), {
      url: `/properties/p1/repairs?year=${CURRENT_YEAR}`,
    });
    await user.click(
      await screen.findByRole("button", { name: /update total to/i }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/will change from \$4,200\.00 to \$3,100\.00/);
    expect(dialog).not.toHaveTextContent(/completed tax year/i);
  });

  it("success sets the total, reloads, and Undo restores the previous total", async () => {
    const user = userEvent.setup();
    let synced = false;
    const api = makeApi(
      (y) =>
        synced
          ? bothSummary(y, {
              entered_total: "3100.00",
              entered_total_rows: [totalRow("tot", "3100.00")],
              remainder: "0.00",
              total_differs_from_itemized: false,
            })
          : bothSummary(y),
      {
        setTotal: vi.fn().mockImplementation(async () => {
          synced = true;
          return summaryOf(COMPLETED_YEAR);
        }),
      } as Partial<ItemizedApi>,
    );
    renderPage(api);
    await user.click(
      await screen.findByRole("button", { name: /update total to/i }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Update total" }));

    await waitFor(() =>
      expect(api.setTotal).toHaveBeenCalledWith(
        "p1",
        "repairs",
        COMPLETED_YEAR,
        "3100.00",
      ),
    );
    expect(
      await screen.findByText("Repairs total updated to $3,100.00"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /update total to/i }),
      ).not.toBeInTheDocument(),
    );

    synced = false;
    await user.click(screen.getByRole("button", { name: /undo/i }));
    await waitFor(() =>
      expect(api.setTotal).toHaveBeenLastCalledWith(
        "p1",
        "repairs",
        COMPLETED_YEAR,
        "4200.00",
      ),
    );
    expect(
      await screen.findByText("Repairs total restored to $4,200.00"),
    ).toBeInTheDocument();
  });

  it("failure shows an error toast and refreshes the summary", async () => {
    const user = userEvent.setup();
    const api = makeApi((y) => bothSummary(y), {
      setTotal: vi.fn().mockRejectedValue(new Error("boom")),
    } as Partial<ItemizedApi>);
    renderPage(api);
    await user.click(
      await screen.findByRole("button", { name: /update total to/i }),
    );
    const dialog = await screen.findByRole("dialog");
    const loadsBefore = api.getSummary.mock.calls.length;
    await user.click(within(dialog).getByRole("button", { name: "Update total" }));

    expect(
      await screen.findByText("Could not update repairs total"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(api.getSummary.mock.calls.length).toBeGreaterThan(loadsBefore),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /undo/i }),
    ).not.toBeInTheDocument();
  });

  it("cancel makes no change", async () => {
    const user = userEvent.setup();
    const api = makeApi((y) => bothSummary(y));
    renderPage(api);
    await user.click(
      await screen.findByRole("button", { name: /update total to/i }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(api.setTotal).not.toHaveBeenCalled();
  });
});

describe("ItemizedExpensesPage: multi-row total (Req 8.6, 9.8)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("explains the state, disables total actions, and hides sync", async () => {
    renderPage(
      makeApi((y) =>
        bothSummary(y, {
          entered_total: "5000.00",
          entered_total_rows: [
            totalRow("t1", "4200.00"),
            totalRow("t2", "800.00"),
          ],
          remainder: "1900.00",
          line_total: "5000.00",
        }),
      ),
    );
    await screen.findByText(/2 repairs total rows/i);
    expect(screen.getByRole("button", { name: "Edit total" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove total" })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: /update total to/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /transactions page/i })).toHaveAttribute(
      "href",
      `/properties/p1/transactions?year=${COMPLETED_YEAR}`,
    );
  });
});

describe("ItemizedExpensesPage: imported total (Req 7.10)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the Imported badge and the re-import hint", async () => {
    renderPage(
      makeApi((y) =>
        summaryOf(y, {
          entered_total: "4200.00",
          entered_total_rows: [totalRow("tot", "4200.00", { imported: true })],
          remainder: "4200.00",
          line_total: "4200.00",
          line_source: "entered_total",
        }),
      ),
    );
    expect(await screen.findByText("Imported")).toBeInTheDocument();
    expect(
      screen.getByText(
        new RegExp(
          `re-importing a schedule e for ${COMPLETED_YEAR} replaces this imported total`,
          "i",
        ),
      ),
    ).toBeInTheDocument();
  });

  it("confirms (no Undo) when removing an imported total", async () => {
    const user = userEvent.setup();
    const api = makeApi((y) =>
      summaryOf(y, {
        entered_total: "4200.00",
        entered_total_rows: [totalRow("tot", "4200.00", { imported: true })],
        remainder: "4200.00",
        line_total: "4200.00",
        line_source: "entered_total",
      }),
    );
    renderPage(api);
    await user.click(await screen.findByRole("button", { name: "Remove total" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/came from a schedule e import/i);
    expect(api.removeTotal).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Remove total" }));
    await waitFor(() =>
      expect(api.removeTotal).toHaveBeenCalledWith("p1", "repairs", COMPLETED_YEAR),
    );
    expect(await screen.findByText("Repairs total removed")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /undo/i }),
    ).not.toBeInTheDocument();
  });
});

describe("ItemizedExpensesPage: total set and Undo (Req 8.1, 8.3, 8.8, 8.9)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sets a total, and Undo removes it again", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);
    await user.click(await screen.findByRole("button", { name: "Set total" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/repairs total for/i), "99.5");
    await user.click(within(dialog).getByRole("button", { name: "Set total" }));

    await waitFor(() =>
      expect(api.setTotal).toHaveBeenCalledWith(
        "p1",
        "repairs",
        COMPLETED_YEAR,
        "99.50",
      ),
    );
    expect(await screen.findByText("Repairs total set to $99.50")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /undo/i }));
    await waitFor(() =>
      expect(api.removeTotal).toHaveBeenCalledWith("p1", "repairs", COMPLETED_YEAR),
    );
  });

  it("editing a total, then Undo, sets the previous amount", async () => {
    const user = userEvent.setup();
    const api = makeApi((y) =>
      summaryOf(y, {
        entered_total: "4200.00",
        entered_total_rows: [totalRow("tot", "4200.00")],
        remainder: "4200.00",
        line_total: "4200.00",
        line_source: "entered_total",
      }),
    );
    renderPage(api);
    await user.click(await screen.findByRole("button", { name: "Edit total" }));
    const dialog = await screen.findByRole("dialog");
    const input = within(dialog).getByLabelText(/repairs total for/i);
    await user.clear(input);
    await user.type(input, "5000");
    await user.click(within(dialog).getByRole("button", { name: "Save total" }));

    await waitFor(() =>
      expect(api.setTotal).toHaveBeenCalledWith(
        "p1",
        "repairs",
        COMPLETED_YEAR,
        "5000.00",
      ),
    );
    await user.click(await screen.findByRole("button", { name: /undo/i }));
    await waitFor(() =>
      expect(api.setTotal).toHaveBeenLastCalledWith(
        "p1",
        "repairs",
        COMPLETED_YEAR,
        "4200.00",
      ),
    );
  });

  it("shows a server field error next to the amount", async () => {
    const user = userEvent.setup();
    const api = makeApi(undefined, {
      setTotal: vi
        .fn()
        .mockRejectedValue(
          new ApiError(400, "bad", { field: "total", message: "Total rejected." }),
        ),
    } as Partial<ItemizedApi>);
    renderPage(api);
    await user.click(await screen.findByRole("button", { name: "Set total" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/repairs total for/i), "10");
    await user.click(within(dialog).getByRole("button", { name: "Set total" }));
    expect(
      (await within(dialog).findAllByText("Total rejected."))[0],
    ).toBeInTheDocument();
  });

  it("removes an unimported total with no receipts using Undo, which sets it again", async () => {
    const user = userEvent.setup();
    const api = makeApi((y) =>
      summaryOf(y, {
        entered_total: "4200.00",
        entered_total_rows: [totalRow("tot", "4200.00")],
        remainder: "4200.00",
        line_total: "4200.00",
        line_source: "entered_total",
      }),
    );
    renderPage(api);
    await user.click(await screen.findByRole("button", { name: "Remove total" }));

    await waitFor(() =>
      expect(api.removeTotal).toHaveBeenCalledWith("p1", "repairs", COMPLETED_YEAR),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /undo/i }));
    await waitFor(() =>
      expect(api.setTotal).toHaveBeenCalledWith(
        "p1",
        "repairs",
        COMPLETED_YEAR,
        "4200.00",
      ),
    );
  });
});

describe("ItemizedExpensesPage: entries (Req 2.1, 15.1, 15.2, 15.5)", () => {
  beforeEach(() => vi.clearAllMocks());

  const withEntry = (y: number) =>
    summaryOf(y, {
      itemized_sum: "620.00",
      itemized_count: 1,
      entries: [entry("e1", { notes: "Invoice 1182" })],
      line_total: "620.00",
      line_source: "itemized",
    });

  it("adds an entry with the right body", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);
    await screen.findByText(/no repairs yet/i);
    await user.click(screen.getAllByRole("button", { name: /add repair/i })[0]);
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/^amount/i), "150");
    await user.type(
      within(dialog).getByLabelText(/description \/ vendor/i),
      "  Gutter fix ",
    );
    await user.click(within(dialog).getByRole("button", { name: "Add entry" }));

    await waitFor(() => expect(api.createEntry).toHaveBeenCalledTimes(1));
    const [propertyId, categoryId, input] = api.createEntry.mock.calls[0];
    expect(propertyId).toBe("p1");
    expect(categoryId).toBe("repairs");
    expect(input).toMatchObject({ amount: "150.00", description: "Gutter fix" });
    expect(input.date.startsWith(`${COMPLETED_YEAR}-`)).toBe(true);
    expect(await screen.findByText("Entry added")).toBeInTheDocument();
  });

  it("deletes immediately with Undo when there are no receipts", async () => {
    const user = userEvent.setup();
    const api = makeApi(withEntry);
    const receiptsApi = makeReceiptsApi();
    renderPage(api, { receiptsApi });
    await user.click(
      await screen.findByRole("button", { name: /^delete .*from .*-03-10/i }),
    );

    await waitFor(() =>
      expect(api.deleteEntry).toHaveBeenCalledWith("p1", "repairs", "e1"),
    );
    expect(receiptsApi.listReceipts).toHaveBeenCalledWith("p1", "e1");
    expect(await screen.findByText("Entry deleted")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /undo/i }));
    await waitFor(() =>
      expect(api.createEntry).toHaveBeenCalledWith("p1", "repairs", {
        date: `${COMPLETED_YEAR}-03-10`,
        amount: "620.00",
        description: "Plumber",
        notes: "Invoice 1182",
      }),
    );
    expect(await screen.findByText("Entry restored")).toBeInTheDocument();
  });

  it("confirms with no Undo when the entry has receipts", async () => {
    const user = userEvent.setup();
    const api = makeApi(withEntry);
    const receiptsApi = makeReceiptsApi({
      listReceipts: vi.fn().mockResolvedValue([{ id: "r1" }]),
    } as Partial<TransactionsApi>);
    renderPage(api, { receiptsApi });
    await user.click(
      await screen.findByRole("button", { name: /^delete .*from .*-03-10/i }),
    );

    const dialog = await screen.findByRole("dialog");
    expect(api.deleteEntry).not.toHaveBeenCalled();
    expect(dialog).toHaveTextContent(/receipt/i);
    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));
    await waitFor(() => expect(api.deleteEntry).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Entry deleted")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /undo/i }),
    ).not.toBeInTheDocument();
  });

  it("confirms when the receipt lookup fails, and cancel deletes nothing", async () => {
    const user = userEvent.setup();
    const api = makeApi(withEntry);
    const receiptsApi = makeReceiptsApi({
      listReceipts: vi.fn().mockRejectedValue(new Error("boom")),
    } as Partial<TransactionsApi>);
    renderPage(api, { receiptsApi });
    await user.click(
      await screen.findByRole("button", { name: /^delete .*from .*-03-10/i }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));
    expect(api.deleteEntry).not.toHaveBeenCalled();
  });
});

describe("ItemizedExpensesPage: second definition (Req 11.5)", () => {
  beforeEach(() => vi.clearAllMocks());

  const SUPPLIES: ItemizedPageDefinition = {
    categoryId: "supplies",
    tabLabel: "Supplies",
    line: 15,
    entryNoun: "supply",
    description: "Supplies for the year.",
    capitalImprovementNote: false,
  };

  it("renders from the definition with no Repairs-specific text", async () => {
    const api = makeApi((y) =>
      summaryOf(y, { category_id: "supplies", label: "Supplies", schedule_e_line: 15 }),
    );
    renderPage(api, { definition: SUPPLIES });

    expect(
      await screen.findByText("Line 15 has no amount for this year"),
    ).toBeInTheDocument();
    expect(api.getSummary).toHaveBeenCalledWith(
      "p1",
      "supplies",
      COMPLETED_YEAR,
      expect.anything(),
    );
    expect(screen.getByRole("heading", { name: "Supplies", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add supply/i })).toBeInTheDocument();
    expect(screen.getByText(/no itemized supply entries/i)).toBeInTheDocument();
    expect(screen.queryByText(/repairs total|itemized repair/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "depreciable assets" }),
    ).not.toBeInTheDocument();
  });
});

describe("ItemizedExpensesPage: new=1 parameter", () => {
  it("opens the add entry dialog once after the load", async () => {
    renderPage(makeApi(), { url: "/properties/p1/repairs?new=1" });
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAccessibleName(/add repair/i);
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });
});
