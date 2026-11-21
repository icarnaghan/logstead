import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import CarryforwardPage from "./CarryforwardPage";
import ReportsPage, { type ReportsApi } from "./ReportsPage";
import type {
  CarryforwardApi,
  ReconciledYear,
  ReconciliationSummary,
} from "../api/carryforward";
import type { ScheduleEReport } from "../api/reports";
import { latestCompletedTaxYear } from "../lib/taxYears";
import { ToastProvider } from "../components/ui";
import { ThemeProvider } from "../theme/ThemeProvider";

// ReportsPage sizes its year range from the property's assets and activity;
// stub both loaders so no network is attempted.
vi.mock("../api/assets", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/assets")>()),
  listAssets: vi.fn().mockResolvedValue([]),
}));
vi.mock("../api/properties", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/properties")>()),
  getEarliestDataYear: vi.fn().mockResolvedValue(null),
}));

/**
 * Load rollout tests for ReportsPage and CarryforwardPage (Requirements
 * 14.1-14.4, 14.6-14.8): skeleton only before the first load, content stays
 * mounted during a refresh, a failed refresh shows a compact error over stale
 * content, and a failed first load shows a full error whose Retry re-runs the
 * failed request.
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

describe("ReportsPage load rollout", () => {
  const LATEST = latestCompletedTaxYear();
  const OTHER = LATEST - 1;
  const YEARS = [LATEST, OTHER];

  const report: ScheduleEReport = {
    header: {
      property_id: "prop-1",
      property_name: "Maple Duplex",
      address: "123 Maple St, Springfield",
      property_type: "Multi-Family",
      tax_year: LATEST,
      fair_rental_days: 300,
      personal_use_days: 5,
    },
    lines: [
      { line: 3, label: "Rents received", kind: "income", total: "24000.00" },
    ],
    other_items: [],
    totals: {
      total_income: "24000.00",
      total_expenses: "0.00",
      net: "24000.00",
    },
    line12: {
      source: "transaction-entered",
      superseded_manual_interest: { amount: "0.00", count: 0 },
    },
  };

  function renderPage(getReport: ReportsApi["getReport"]) {
    render(
      <ThemeProvider>
        <ToastProvider>
        <MemoryRouter initialEntries={["/properties/prop-1/reports"]}>
          <Routes>
            <Route
              path="/properties/:propertyId/reports"
              element={<ReportsPage api={{ getReport }} years={YEARS} />}
            />
          </Routes>
        </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>,
    );
  }

  it("shows only a skeleton region before the first load resolves", async () => {
    const d = deferred<ScheduleEReport>();
    renderPage(() => d.promise);

    expect(
      screen.getByRole("status", { name: /loading report/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Maple Duplex")).not.toBeInTheDocument();

    d.resolve(report);
    expect(await screen.findByText("Maple Duplex")).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: /loading report/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps the report mounted while another year loads", async () => {
    const user = userEvent.setup();
    const second = deferred<ScheduleEReport>();
    const getReport = vi
      .fn()
      .mockResolvedValueOnce(report)
      .mockReturnValueOnce(second.promise);
    renderPage(getReport);
    await screen.findByText("Maple Duplex");

    await user.selectOptions(screen.getByLabelText(/tax year/i), String(OTHER));

    expect(getReport).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Maple Duplex")).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: /loading report/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Refreshing")).toBeInTheDocument();

    second.resolve(report);
    await waitFor(() =>
      expect(screen.queryByText(/^refreshing$/i)).not.toBeInTheDocument(),
    );
  });

  it("shows a compact error over stale content when a refresh fails, and Retry re-runs it", async () => {
    const user = userEvent.setup();
    const getReport = vi
      .fn()
      .mockResolvedValueOnce(report)
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(report);
    renderPage(getReport);
    await screen.findByText("Maple Duplex");

    await user.selectOptions(screen.getByLabelText(/tax year/i), String(OTHER));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not load the report/i);
    expect(screen.getByText("Maple Duplex")).toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
    expect(getReport).toHaveBeenCalledTimes(3);
    expect(getReport).toHaveBeenLastCalledWith("prop-1", OTHER);
    expect(screen.getByText("Maple Duplex")).toBeInTheDocument();
  });

  it("shows a full error on first-load failure and Retry re-runs the request", async () => {
    const user = userEvent.setup();
    const getReport = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(report);
    renderPage(getReport);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not load the report/i);
    expect(screen.queryByText("Maple Duplex")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: /loading report/i }),
    ).not.toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("Maple Duplex")).toBeInTheDocument();
    expect(getReport).toHaveBeenCalledTimes(2);
    expect(getReport).toHaveBeenLastCalledWith("prop-1", LATEST);
  });
});

describe("CarryforwardPage load rollout", () => {
  function year(overrides: Partial<ReconciledYear> = {}): ReconciledYear {
    return {
      tax_year: 2023,
      schedule_e_net: "100.00",
      expected_carry_in: "300.00",
      expected_carryforward: "200.00",
      reported_carryforward: null,
      allowed_loss: "0.00",
      fully_allowed: false,
      status: "unreported",
      drift: null,
      carried_from_year: null,
      ...overrides,
    };
  }

  const summary: ReconciliationSummary = {
    opening_balance: "0.00",
    has_data: true,
    next_year: 2024,
    next_year_expected_carry_in: "200.00",
    status_tolerance: "2.00",
    years: [year()],
  };

  function makeApi(
    getReconciliation: CarryforwardApi["getReconciliation"],
  ): CarryforwardApi {
    return {
      getReconciliation,
      setReported: vi.fn().mockResolvedValue(undefined),
      clearReported: vi.fn().mockResolvedValue(undefined),
      setOpeningBalance: vi.fn().mockResolvedValue(undefined),
      setYear: vi.fn().mockResolvedValue(undefined),
      setAllowedLoss: vi.fn().mockResolvedValue(undefined),
      clearAllowedLoss: vi.fn().mockResolvedValue(undefined),
      setFullyAllowed: vi.fn().mockResolvedValue(undefined),
    } as unknown as CarryforwardApi;
  }

  function renderPage(api: CarryforwardApi) {
    render(
      <MemoryRouter initialEntries={["/carryforward"]}>
        <CarryforwardPage api={api} />
      </MemoryRouter>,
    );
  }

  /** Types a reported value for 2023 and saves, which triggers a reload. */
  async function saveReported(user: ReturnType<typeof userEvent.setup>) {
    const row = (await screen.findByText("2023")).closest("tr") as HTMLElement;
    await user.type(
      within(row).getByLabelText(/prior years' unallowed losses for 2023/i),
      "200.00",
    );
    await user.click(within(row).getByRole("button", { name: /save/i }));
  }

  it("shows only a skeleton region before the first load resolves", async () => {
    const d = deferred<ReconciliationSummary>();
    renderPage(makeApi(() => d.promise));

    expect(
      screen.getByRole("status", { name: /loading reconciliation/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    d.resolve(summary);
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: /loading reconciliation/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps the table mounted while a reload is in flight", async () => {
    const user = userEvent.setup();
    const second = deferred<ReconciliationSummary>();
    const getReconciliation = vi
      .fn()
      .mockResolvedValueOnce(summary)
      .mockReturnValueOnce(second.promise);
    renderPage(makeApi(getReconciliation));
    await screen.findByRole("table");

    await saveReported(user);

    await waitFor(() => expect(getReconciliation).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: /loading reconciliation/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Refreshing")).toBeInTheDocument();

    second.resolve(summary);
    await waitFor(() =>
      expect(screen.queryByText("Refreshing")).not.toBeInTheDocument(),
    );
  });

  it("shows a compact error over stale content when a reload fails, and Retry re-runs it", async () => {
    const user = userEvent.setup();
    const getReconciliation = vi
      .fn()
      .mockResolvedValueOnce(summary)
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(summary);
    renderPage(makeApi(getReconciliation));
    await screen.findByRole("table");

    await saveReported(user);

    const alert = await screen.findByText(
      /could not load the carryforward reconciliation/i,
    );
    expect(screen.getByRole("table")).toBeInTheDocument();

    await user.click(
      within(alert.closest('[role="alert"]') as HTMLElement).getByRole(
        "button",
        { name: /retry/i },
      ),
    );

    await waitFor(() => expect(getReconciliation).toHaveBeenCalledTimes(3));
    await waitFor(() =>
      expect(
        screen.queryByText(/could not load the carryforward reconciliation/i),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("shows a full error on first-load failure and Retry re-runs the request", async () => {
    const user = userEvent.setup();
    const getReconciliation = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(summary);
    renderPage(makeApi(getReconciliation));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      /could not load the carryforward reconciliation/i,
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(getReconciliation).toHaveBeenCalledTimes(2);
  });
});
