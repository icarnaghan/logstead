import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BusinessDetailPage from "./BusinessDetailPage";
import PropertyDetailPage from "./PropertyDetailPage";
import PropertyLayout from "../components/PropertyLayout";
import { ApiClient } from "../lib/apiClient";
import {
  resetBusinessesClient,
  setBusinessesClient,
  type BusinessWithLinks,
} from "../api/businesses";
import type { Property } from "../api/properties";
import type { ScheduleEReport } from "../api/reports";
import { latestCompletedTaxYear } from "../lib/taxYears";
import { ThemeProvider } from "../theme/ThemeProvider";

/**
 * Load rollout tests for the detail pages (Requirements 14.1-14.4, 14.6-14.8).
 *
 * Neither detail page has a user path that refreshes already-loaded primary
 * data (Business edits update local state; the property context only reloads
 * through Retry), so the "content stays mounted" and "stale compact error"
 * cases are covered where a refresh path exists: the property overview's
 * year-driven report tiles.
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

describe("BusinessDetailPage load rollout", () => {
  const business: BusinessWithLinks = {
    id: "b1",
    user_id: "u1",
    legal_name: "Acme Holdings LLC",
    entity_type: "llc",
    tax_year_end: "12-31",
    linked_properties: [{ id: "p1", name: "123 Oak Street" }],
  };

  beforeEach(() => {
    // The embedded documents list resolves empty instead of hitting the network.
    const fetchImpl: typeof fetch = async () =>
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    setBusinessesClient(new ApiClient({ baseUrl: "http://test", fetchImpl }));
  });

  afterEach(() => resetBusinessesClient());

  function renderPage(load: () => Promise<BusinessWithLinks>) {
    render(
      <MemoryRouter initialEntries={["/businesses/b1"]}>
        <Routes>
          <Route
            path="/businesses/:businessId"
            element={<BusinessDetailPage load={load} />}
          />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("shows only a skeleton region before the first load resolves", async () => {
    const d = deferred<BusinessWithLinks>();
    renderPage(() => d.promise);

    expect(
      screen.getByRole("status", { name: /loading business/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Linked properties")).not.toBeInTheDocument();

    d.resolve(business);
    expect(await screen.findByText("Linked properties")).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: /loading business/i }),
    ).not.toBeInTheDocument();
  });

  it("shows a full error on first-load failure and Retry re-runs the request", async () => {
    const user = userEvent.setup();
    const load = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(business);
    renderPage(load);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not load this business/i);
    expect(screen.queryByText("Linked properties")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: /loading business/i }),
    ).not.toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("Linked properties")).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("PropertyDetailPage load rollout", () => {
  const property: Property = {
    id: "p1",
    user_id: "u1",
    name: "Maple Duplex",
    address_text: "1 Maple St, Springfield",
    property_type: "Single Family",
  };

  const report: ScheduleEReport = {
    header: {
      property_id: "p1",
      property_name: "Maple Duplex",
      address: "1 Maple St, Springfield",
      property_type: "Single Family",
      tax_year: 2024,
      fair_rental_days: 300,
      personal_use_days: 5,
    },
    lines: [
      { line: 3, label: "Rents received", kind: "income", total: "24000.00" },
      { line: 18, label: "Depreciation", kind: "expense", total: "5833.33" },
    ],
    other_items: [],
    totals: {
      total_income: "24000.00",
      total_expenses: "7175.33",
      net: "16824.67",
    },
    line12: {
      source: "transaction-entered",
      superseded_manual_interest: { amount: "0.00", count: 0 },
    },
  };

  function renderPage(options: {
    loadProperty: () => Promise<Property>;
    loadReport?: (propertyId: string, taxYear: number) => Promise<ScheduleEReport>;
  }) {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/properties/p1"]}>
          <Routes>
            <Route
              path="/properties/:propertyId"
              element={<PropertyLayout load={options.loadProperty} />}
            >
              <Route
                index
                element={
                  <PropertyDetailPage
                    loadReport={options.loadReport ?? (async () => report)}
                    loadPhotos={async () => []}
                    loadAssets={async () => []}
                    loadEarliestYear={async () => null}
                    loadNote={async () => ""}
                    saveNote={async (_id, text) => text}
                  />
                }
              />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );
  }

  it("shows only a skeleton region before the property loads", async () => {
    const d = deferred<Property>();
    renderPage({ loadProperty: () => d.promise });

    expect(
      screen.getByRole("status", { name: /loading property/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText("1 Maple St, Springfield")).not.toBeInTheDocument();

    d.resolve(property);
    expect(
      await screen.findByText("1 Maple St, Springfield"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: /loading property/i }),
    ).not.toBeInTheDocument();
  });

  it("shows a full error on first-load failure and Retry re-runs the request", async () => {
    const user = userEvent.setup();
    const loadProperty = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(property);
    renderPage({ loadProperty });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not load this property/i);
    expect(screen.queryByText("1 Maple St, Springfield")).not.toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    expect(
      await screen.findByText("1 Maple St, Springfield"),
    ).toBeInTheDocument();
    expect(loadProperty).toHaveBeenCalledTimes(2);
  });

  it("keeps the page mounted while a new year's report loads, then shows a compact error over it if it fails", async () => {
    const user = userEvent.setup();
    const second = deferred<ScheduleEReport>();
    const loadReport = vi
      .fn()
      .mockResolvedValueOnce(report)
      .mockReturnValueOnce(second.promise);
    renderPage({ loadProperty: async () => property, loadReport });
    await screen.findByText("1 Maple St, Springfield");
    await screen.findByText("Total income");

    await user.selectOptions(
      screen.getByLabelText(/tax year/i),
      String(latestCompletedTaxYear() - 1),
    );

    // The page-level skeleton never returns; only the tile shows its loading text.
    expect(loadReport).toHaveBeenCalledTimes(2);
    expect(screen.getByText("1 Maple St, Springfield")).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: /loading property/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Loading totals…")).toBeInTheDocument();

    second.reject(new Error("boom"));
    await waitFor(() =>
      expect(
        screen.getAllByText(/could not load the report/i).length,
      ).toBeGreaterThan(0),
    );
    expect(screen.getByText("1 Maple St, Springfield")).toBeInTheDocument();
  });
});
