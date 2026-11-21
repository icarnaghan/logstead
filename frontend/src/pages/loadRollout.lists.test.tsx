import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import AssetsPage, { type AssetsApi } from "./AssetsPage";
import LoansPage, { type LoansApi } from "./LoansPage";
import TransactionsPage from "./TransactionsPage";
import type { DepreciableAsset } from "../api/assets";
import type { Loan } from "../api/loans";
import type { Category, Transaction, TransactionsApi } from "../api/transactions";
import { ToastProvider } from "../components/ui";
import { latestCompletedTaxYear } from "../lib/taxYears";
import { ThemeProvider } from "../theme/ThemeProvider";

// TransactionsPage sizes its tax-year range from assets and activity; stub the
// module-level loaders so no network is attempted. AssetsPage and LoansPage get
// their API through props and are unaffected.
vi.mock("../api/assets", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/assets")>()),
  listAssets: vi.fn().mockResolvedValue([]),
}));
vi.mock("../api/properties", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/properties")>()),
  getEarliestDataYear: vi.fn().mockResolvedValue(null),
}));


/**
 * Load rollout tests for AssetsPage, TransactionsPage, and LoansPage
 * (Requirements 14.1-14.4, 14.6-14.8): skeleton only before the first load,
 * content stays mounted during a refresh, a failed refresh shows a compact
 * error over stale content, a failed first load shows a full error whose Retry
 * re-runs the failed request, and the nested schedule panels offer a compact
 * error with a Retry that re-runs the schedule load.
 */

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("AssetsPage load rollout", () => {
  const asset: DepreciableAsset = {
    id: "a1",
    description: "Roof replacement",
    cost_basis: "10000.00",
    placed_in_service_date: "2023-06-15",
    recovery_period_years: 27.5,
    created_at: "2023-06-15T00:00:00Z",
    updated_at: "2023-06-15T00:00:00Z",
  };

  function makeApi(overrides: Partial<AssetsApi> = {}): AssetsApi {
    return {
      listAssets: vi.fn().mockResolvedValue([asset]),
      createAsset: vi.fn().mockResolvedValue(asset),
      updateAsset: vi.fn().mockResolvedValue(asset),
      deleteAsset: vi.fn().mockResolvedValue(undefined),
      getSchedule: vi.fn().mockResolvedValue([]),
      ...overrides,
    };
  }

  function renderPage(api: AssetsApi) {
    render(
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={["/properties/prop-1/assets"]}>
            <Routes>
              <Route
                path="/properties/:propertyId/assets"
                element={<AssetsPage api={api} />}
              />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>,
    );
  }

  async function deleteFirstAsset(user: ReturnType<typeof userEvent.setup>) {
    const [button] = await screen.findAllByRole("button", { name: "Delete" });
    await user.click(button);
  }

  it("shows only a skeleton region before the first load resolves", async () => {
    const d = deferred<DepreciableAsset[]>();
    renderPage(makeApi({ listAssets: () => d.promise }));

    expect(
      screen.getByRole("status", { name: /loading assets/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Roof replacement")).not.toBeInTheDocument();
    expect(screen.queryByText(/no assets yet/i)).not.toBeInTheDocument();

    d.resolve([asset]);
    expect((await screen.findAllByText("Roof replacement")).length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("status", { name: /loading assets/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps the list mounted while a refresh is in flight", async () => {
    const user = userEvent.setup();
    const second = deferred<DepreciableAsset[]>();
    const listAssets = vi
      .fn()
      .mockResolvedValueOnce([asset])
      .mockReturnValueOnce(second.promise);
    renderPage(makeApi({ listAssets }));

    await deleteFirstAsset(user);

    await waitFor(() => expect(listAssets).toHaveBeenCalledTimes(2));
    expect(screen.getAllByText("Roof replacement").length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("status", { name: /loading assets/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Refreshing")).toBeInTheDocument();

    second.resolve([]);
    await waitFor(() =>
      expect(screen.queryByText("Refreshing")).not.toBeInTheDocument(),
    );
  });

  it("shows a compact error over stale content when a refresh fails, and Retry re-runs it", async () => {
    const user = userEvent.setup();
    const listAssets = vi
      .fn()
      .mockResolvedValueOnce([asset])
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce([asset]);
    renderPage(makeApi({ listAssets }));

    await deleteFirstAsset(user);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not load depreciable assets/i);
    expect(screen.getAllByText("Roof replacement").length).toBeGreaterThan(0);

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(listAssets).toHaveBeenCalledTimes(3));
    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
  });

  it("shows a full error on first-load failure and Retry re-runs the request", async () => {
    const user = userEvent.setup();
    const listAssets = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce([asset]);
    renderPage(makeApi({ listAssets }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not load depreciable assets/i);
    expect(screen.queryByText("Roof replacement")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: /loading assets/i }),
    ).not.toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    expect((await screen.findAllByText("Roof replacement")).length).toBeGreaterThan(0);
    expect(listAssets).toHaveBeenCalledTimes(2);
  });

  it("shows a compact schedule error whose Retry re-runs the schedule load", async () => {
    const user = userEvent.setup();
    const getSchedule = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce([]);
    renderPage(makeApi({ getSchedule }));

    const [view] = await screen.findAllByRole("button", {
      name: "View schedule",
    });
    await user.click(view);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/unable to load the depreciation schedule/i);
    expect(screen.getAllByText("Roof replacement").length).toBeGreaterThan(0);

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
    expect(getSchedule).toHaveBeenCalledTimes(2);
    expect(getSchedule).toHaveBeenLastCalledWith("prop-1", "a1");
  });
});

describe("TransactionsPage load rollout", () => {
  const categories: Category[] = [
    {
      id: "repairs",
      kind: "expense",
      label: "Repairs",
      schedule_e_line: "14",
      requires_description: false,
    },
  ];
  const tx: Transaction = {
    id: "t1",
    property_id: "p1",
    date: "2024-01-05",
    amount: "250.00",
    type: "expense",
    category_id: "repairs",
    description: "Fix sink",
  };
  const OTHER_YEAR = latestCompletedTaxYear() - 1;

  function makeApi(listTransactions: TransactionsApi["listTransactions"]) {
    return {
      listCategories: vi.fn().mockResolvedValue(categories),
      listTransactions,
      createTransaction: vi.fn(),
      getTransaction: vi.fn(),
      updateTransaction: vi.fn(),
      deleteTransaction: vi.fn(),
      attachReceipt: vi.fn(),
      uploadToPresignedUrl: vi.fn(),
      listReceipts: vi.fn().mockResolvedValue([]),
      deleteReceipt: vi.fn(),
    } as unknown as TransactionsApi;
  }

  function renderPage(api: TransactionsApi) {
    render(
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

  async function changeYear(user: ReturnType<typeof userEvent.setup>) {
    await user.selectOptions(
      screen.getByLabelText(/tax year/i),
      String(OTHER_YEAR),
    );
  }

  it("shows only a skeleton region before the first load resolves", async () => {
    const d = deferred<Transaction[]>();
    renderPage(makeApi(() => d.promise));

    expect(
      screen.getByRole("status", { name: /loading transactions/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/no transactions yet/i)).not.toBeInTheDocument();

    d.resolve([tx]);
    expect((await screen.findAllByText("Fix sink")).length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("status", { name: /loading transactions/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps rows mounted while a tax-year change reloads", async () => {
    const user = userEvent.setup();
    const second = deferred<Transaction[]>();
    const listTransactions = vi
      .fn()
      .mockResolvedValueOnce([tx])
      .mockReturnValueOnce(second.promise);
    renderPage(makeApi(listTransactions));
    await screen.findAllByText("Fix sink");

    await changeYear(user);

    await waitFor(() => expect(listTransactions).toHaveBeenCalledTimes(2));
    expect(screen.getAllByText("Fix sink").length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("status", { name: /loading transactions/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Refreshing")).toBeInTheDocument();

    second.resolve([tx]);
    await waitFor(() =>
      expect(screen.queryByText("Refreshing")).not.toBeInTheDocument(),
    );
  });

  it("shows a compact error over stale rows when a refresh fails, and Retry re-runs it", async () => {
    const user = userEvent.setup();
    const listTransactions = vi
      .fn()
      .mockResolvedValueOnce([tx])
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce([tx]);
    renderPage(makeApi(listTransactions));
    await screen.findAllByText("Fix sink");

    await changeYear(user);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not load transactions/i);
    expect(screen.getAllByText("Fix sink").length).toBeGreaterThan(0);

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(listTransactions).toHaveBeenCalledTimes(3));
    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
    expect(listTransactions.mock.calls[2][1]).toBe(OTHER_YEAR);
  });

  it("shows a full error on first-load failure and Retry re-runs the request", async () => {
    const user = userEvent.setup();
    const listTransactions = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce([tx]);
    renderPage(makeApi(listTransactions));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not load transactions/i);
    expect(screen.queryByText("Fix sink")).not.toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    expect((await screen.findAllByText("Fix sink")).length).toBeGreaterThan(0);
    expect(listTransactions).toHaveBeenCalledTimes(2);
  });
});

describe("LoansPage load rollout", () => {
  const loan: Loan = {
    id: "loan-1",
    property_id: "prop-1",
    description: "Main mortgage",
    annual_interest_rate: "6.000",
    monthly_payment: "1498.88",
    anchor_balance: "200000.00",
    anchor_date: "2023-06-15",
    extra_principal: "0.00",
    original_principal: null,
    closing_date: null,
    payoff_date: null,
    include_in_report: true,
    interest_overrides: {},
    remaining_payments: 200,
    next_payment_date: "2023-07-15",
    projected_payoff_date: "2040-02-15",
    payoff_balance: null,
    status: "active",
    created_at: "2023-01-01T00:00:00Z",
    updated_at: "2023-01-01T00:00:00Z",
  };

  const emptySchedule = {
    loan_id: "loan-1",
    estimate: true,
    payoff_balance: null,
    payments: [],
    yearly: [],
  };

  function makeApi(overrides: Partial<LoansApi> = {}): LoansApi {
    return {
      listLoans: vi.fn().mockResolvedValue([loan]),
      createLoan: vi.fn().mockResolvedValue(loan),
      updateLoan: vi.fn().mockResolvedValue(loan),
      deleteLoan: vi.fn().mockResolvedValue(undefined),
      getLoanSchedule: vi.fn().mockResolvedValue(emptySchedule),
      setInterestOverride: vi.fn(),
      clearInterestOverride: vi.fn(),
      getLine12Impact: vi.fn().mockResolvedValue([]),
      ...overrides,
    };
  }

  function renderPage(api: LoansApi) {
    render(
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={["/properties/prop-1/loans"]}>
            <Routes>
              <Route
                path="/properties/:propertyId/loans"
                element={<LoansPage api={api} />}
              />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>,
    );
  }

  async function deleteFirstLoan(user: ReturnType<typeof userEvent.setup>) {
    const [button] = await screen.findAllByRole("button", {
      name: "Delete Main mortgage",
    });
    await user.click(button);
  }

  it("shows only a skeleton region before the first load resolves", async () => {
    const d = deferred<Loan[]>();
    renderPage(makeApi({ listLoans: () => d.promise }));

    expect(
      screen.getByRole("status", { name: /loading loans/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Main mortgage")).not.toBeInTheDocument();

    d.resolve([loan]);
    expect((await screen.findAllByText("Main mortgage")).length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("status", { name: /loading loans/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps the list mounted while a refresh is in flight", async () => {
    const user = userEvent.setup();
    const second = deferred<Loan[]>();
    const listLoans = vi
      .fn()
      .mockResolvedValueOnce([loan])
      .mockReturnValueOnce(second.promise);
    renderPage(makeApi({ listLoans }));

    await deleteFirstLoan(user);

    await waitFor(() => expect(listLoans).toHaveBeenCalledTimes(2));
    expect(screen.getAllByText("Main mortgage").length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("status", { name: /loading loans/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Refreshing")).toBeInTheDocument();

    second.resolve([]);
    await waitFor(() =>
      expect(screen.queryByText("Refreshing")).not.toBeInTheDocument(),
    );
  });

  it("shows a compact error over stale content when a refresh fails, and Retry re-runs it", async () => {
    const user = userEvent.setup();
    const listLoans = vi
      .fn()
      .mockResolvedValueOnce([loan])
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce([loan]);
    renderPage(makeApi({ listLoans }));

    await deleteFirstLoan(user);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not load your loans/i);
    expect(screen.getAllByText("Main mortgage").length).toBeGreaterThan(0);

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(listLoans).toHaveBeenCalledTimes(3));
    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
  });

  it("shows a full error on first-load failure and Retry re-runs the request", async () => {
    const user = userEvent.setup();
    const listLoans = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce([loan]);
    renderPage(makeApi({ listLoans }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not load your loans/i);
    expect(screen.queryByText("Main mortgage")).not.toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    expect((await screen.findAllByText("Main mortgage")).length).toBeGreaterThan(0);
    expect(listLoans).toHaveBeenCalledTimes(2);
  });

  it("shows a compact schedule error whose Retry re-runs the schedule load", async () => {
    const user = userEvent.setup();
    const getLoanSchedule = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(emptySchedule);
    renderPage(makeApi({ getLoanSchedule }));

    const [select] = await screen.findAllByRole("button", {
      name: "Select Main mortgage",
    });
    await user.click(select);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/unable to load the schedule/i);
    expect(screen.getAllByText("Main mortgage").length).toBeGreaterThan(0);

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
    expect(getLoanSchedule).toHaveBeenCalledTimes(2);
    expect(getLoanSchedule).toHaveBeenLastCalledWith("prop-1", "loan-1");
  });
});
