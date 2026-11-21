import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import BusinessesPage from "./BusinessesPage";
import CombinedReportsPage from "./CombinedReportsPage";
import PropertiesPage from "./PropertiesPage";
import type { Business } from "../api/businesses";
import type { Property } from "../api/properties";
import type { CombinedScheduleEReport } from "../api/reports";
import { ToastProvider } from "../components/ui";
import { ThemeProvider } from "../theme/ThemeProvider";

// The portfolio year-range hook hits the API; stub it (other exports stay real).
vi.mock("../api/properties", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/properties")>()),
  listProperties: vi.fn().mockResolvedValue([]),
  getEarliestDataYear: vi.fn().mockResolvedValue(null),
}));

/**
 * Load rollout tests (Requirements 14.1-14.4, 14.6-14.8): skeleton only before
 * the first load, content stays mounted during a refresh, a failed first load
 * shows a full error whose Retry re-runs the request, and a failed refresh
 * shows a compact error over the stale content.
 *
 * Properties and Businesses only refresh via Retry (no stale-error path), so
 * they cover the first-load cases; the combined report covers all four.
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

const property: Property = {
  id: "p1",
  user_id: "u1",
  name: "Maple Duplex",
  address_text: "1 Maple St",
  property_type: "duplex",
};

const business: Business = {
  id: "b1",
  user_id: "u1",
  legal_name: "Maple Holdings",
  entity_type: "llc",
  tax_year_end: "12-31",
};

describe("PropertiesPage load rollout", () => {
  function renderPage(load: () => Promise<Property[]>) {
    render(
      <ToastProvider>
        <MemoryRouter>
          <PropertiesPage load={load} loadPhotos={async () => []} />
        </MemoryRouter>
      </ToastProvider>,
    );
  }

  it("shows only a skeleton before the first load resolves", async () => {
    const d = deferred<Property[]>();
    renderPage(() => d.promise);

    expect(screen.getByTestId("table-skeleton")).toBeInTheDocument();
    expect(screen.queryByText(/no properties yet/i)).not.toBeInTheDocument();

    d.resolve([property]);
    expect(
      await screen.findByRole("link", { name: "Maple Duplex" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("table-skeleton")).not.toBeInTheDocument();
  });

  it("shows a full error on first-load failure and Retry re-runs the request", async () => {
    const user = userEvent.setup();
    const load = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce([property]);
    renderPage(load);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not load your properties/i);
    expect(screen.queryByTestId("table-skeleton")).not.toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    expect(
      await screen.findByRole("link", { name: "Maple Duplex" }),
    ).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("BusinessesPage load rollout", () => {
  function renderPage(load: () => Promise<Business[]>) {
    render(
      <MemoryRouter>
        <BusinessesPage load={load} />
      </MemoryRouter>,
    );
  }

  it("shows only a skeleton before the first load resolves", async () => {
    const d = deferred<Business[]>();
    renderPage(() => d.promise);

    expect(screen.getByTestId("table-skeleton")).toBeInTheDocument();

    d.resolve([business]);
    expect(
      (await screen.findAllByRole("link", { name: "Maple Holdings" })).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByTestId("table-skeleton")).not.toBeInTheDocument();
  });

  it("shows a full error on first-load failure and Retry re-runs the request", async () => {
    const user = userEvent.setup();
    const load = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce([business]);
    renderPage(load);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not load your businesses/i);

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    expect(
      (await screen.findAllByRole("link", { name: "Maple Holdings" })).length,
    ).toBeGreaterThan(0);
    expect(load).toHaveBeenCalledTimes(2);
  });
});

describe("CombinedReportsPage load rollout", () => {
  const report: CombinedScheduleEReport = {
    tax_year: 2025,
    properties: [],
    totals: { total_income: "100.00", total_expenses: "40.00", net: "60.00" },
    line12: {
      total: "0.00",
      superseded_manual_interest: { amount: "0.00", count: 0 },
    },
  };

  function renderPage(
    loadCombined: (taxYear: number) => Promise<CombinedScheduleEReport>,
  ) {
    render(
      <ThemeProvider>
        <ToastProvider>
        <MemoryRouter initialEntries={["/reports"]}>
          <CombinedReportsPage
            loadCombined={loadCombined}
            years={[2025, 2024]}
          />
        </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>,
    );
  }

  it("shows a skeleton region only before the first load", async () => {
    const d = deferred<CombinedScheduleEReport>();
    renderPage(() => d.promise);

    expect(
      screen.getByRole("status", { name: /loading combined report/i }),
    ).toBeInTheDocument();

    d.resolve(report);
    await screen.findByText("Portfolio totals");
    expect(
      screen.queryByRole("status", { name: /loading combined report/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps the report mounted while a new year loads", async () => {
    const user = userEvent.setup();
    const second = deferred<CombinedScheduleEReport>();
    const load = vi
      .fn()
      .mockResolvedValueOnce(report)
      .mockReturnValueOnce(second.promise);
    renderPage(load);
    await screen.findByText("Portfolio totals");

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");

    expect(load).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Portfolio totals")).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: /loading combined report/i }),
    ).not.toBeInTheDocument();

    second.resolve({ ...report, tax_year: 2024 });
    await waitFor(() =>
      expect(screen.queryByRole("status", { name: /refreshing/i })).toBeNull(),
    );
  });

  it("shows a compact error over stale content when a refresh fails", async () => {
    const user = userEvent.setup();
    const load = vi
      .fn()
      .mockResolvedValueOnce(report)
      .mockRejectedValueOnce(new Error("boom"));
    renderPage(load);
    await screen.findByText("Portfolio totals");

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not load the combined report/i,
    );
    expect(screen.getByText("Portfolio totals")).toBeInTheDocument();
  });

  it("shows a full error on first-load failure and Retry re-runs the request", async () => {
    const user = userEvent.setup();
    const load = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(report);
    renderPage(load);

    const alert = await screen.findByRole("alert");
    expect(screen.queryByText("Portfolio totals")).not.toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("Portfolio totals")).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(2);
    expect(load).toHaveBeenLastCalledWith(2025);
  });
});
