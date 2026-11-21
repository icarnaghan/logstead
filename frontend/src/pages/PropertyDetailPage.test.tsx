import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import PropertyDetailPage from "./PropertyDetailPage";
import PropertyLayout from "../components/PropertyLayout";
import { ThemeProvider } from "../theme/ThemeProvider";
import { ApiError, type Property } from "../api/properties";
import type { ScheduleEReport } from "../api/reports";
import type { DepreciableAsset } from "../api/assets";
import type { ActivityEvent, ActivityPage } from "../api/activity";
import type { PropertyChecklistSummary } from "../api/yearEndChecklist";

/**
 * Tests for the per-property tiled dashboard. It fetches one property and shows
 * a header, income/expense/net and depreciation tiles from the Schedule E
 * report, an editable notes tile, and quicklinks — all driven by a tax-year
 * selector at the top.
 */

const baseProperty: Property = {
  id: "p1",
  user_id: "u1",
  name: "Maple Duplex",
  address_text: "1 Maple St, Springfield",
  property_type: "Single Family",
};

function makeReport(overrides: Partial<ScheduleEReport> = {}): ScheduleEReport {
  return {
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
    ...overrides,
  };
}

interface RenderOptions {
  property?: Property | (() => Promise<Property>);
  loadReport?: (propertyId: string, taxYear: number) => Promise<ScheduleEReport>;
  loadNote?: (propertyId: string) => Promise<string>;
  saveNote?: (propertyId: string, text: string) => Promise<string>;
  loadAssets?: (propertyId: string) => Promise<DepreciableAsset[]>;
  loadEarliestYear?: (propertyId: string) => Promise<number | null>;
  loadChecklistSummary?: (propertyId: string) => Promise<PropertyChecklistSummary>;
  loadActivity?: (propertyId: string) => Promise<ActivityPage>;
}
function makeEvent(n: number): ActivityEvent {
  return {
    id: `e${n}`,
    at: "2025-03-01T12:00:00Z",
    action: "create",
    entity: "transaction",
    record_id: `t${n}`,
    property_id: "p1",
    property_name: "Maple Duplex",
    summary: `Added transaction ${n}`,
    before: null,
    after: null,
    truncated: false,
    restorable: false,
    restored_as: null,
  };
}

const defaultChecklistSummary = async (
  propertyId: string,
): Promise<PropertyChecklistSummary> => ({
  property_id: propertyId,
  years: [
    {
      tax_year: 2024,
      counts: { done: 6, needs_attention: 3, not_applicable: 2, total: 11 },
    },
  ],
});

function renderAt(id: string, options: RenderOptions = {}) {
  const propertyOption = options.property;
  // Identity now flows through the shared property context: `PropertyLayout`
  // fetches the property (via the injected `load`) and provides it to the
  // overview page via `<Outlet context>`, which the page reads through
  // `usePropertyContext()`. The page is the index route under the layout.
  const load: (id: string) => Promise<Property> =
    typeof propertyOption === "function"
      ? propertyOption
      : async () => propertyOption ?? baseProperty;
  return render(
    // The income/expenses tile now renders a chart, which reads
    // `useChartColors → useTheme`; without a ThemeProvider that hook throws.
    <ThemeProvider>
      <MemoryRouter initialEntries={[`/properties/${id}`]}>
        <Routes>
          <Route
            path="/properties/:propertyId"
            element={<PropertyLayout load={load} />}
          >
            <Route
              index
              element={
                <PropertyDetailPage
                  loadReport={options.loadReport ?? (async () => makeReport())}
                  loadPhotos={async () => []}
                  loadAssets={options.loadAssets ?? (async () => [])}
                  loadEarliestYear={
                    options.loadEarliestYear ?? (async () => null)
                  }
                  loadNote={options.loadNote ?? (async () => "")}
                  saveNote={options.saveNote ?? (async (_id, text) => text)}
                  loadChecklistSummary={
                    options.loadChecklistSummary ?? defaultChecklistSummary
                  }
                  loadActivity={
                    options.loadActivity ??
                    (async () => ({ events: [], next_cursor: null }))
                  }
                />
              }
            />
          </Route>
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("PropertyDetailPage dashboard", () => {
  it("renders the property header and quicklinks", async () => {
    renderAt("p1");

    // The page heading is the literal "Overview"; the property name/address is
    // rendered as the subtitle line below it (consistent with the sub-pages).
    expect(
      await screen.findByRole("heading", { name: "Overview" }),
    ).toBeInTheDocument();
    expect(screen.getByText("1 Maple St, Springfield")).toBeInTheDocument();
    // The property name now appears twice: as the breadcrumb's current crumb
    // and as the subtitle line under the "Overview" heading.
    expect(screen.getAllByText("Maple Duplex").length).toBeGreaterThanOrEqual(2);
    // The sub-section quicklinks live in the Quicklinks tile. Scope to it so
    // the identically-labelled Section Tabs (added by this feature) don't make
    // these queries ambiguous.
    const quicklinks = screen.getByRole("region", { name: /quicklinks/i });
    expect(
      within(quicklinks).getByRole("link", { name: /^transactions$/i }),
    ).toHaveAttribute("href", "/properties/p1/transactions");
    expect(
      within(quicklinks).getByRole("link", { name: /depreciable assets/i }),
    ).toHaveAttribute("href", "/properties/p1/assets");
    expect(
      within(quicklinks).getByRole("link", { name: /schedule e report/i }),
    ).toHaveAttribute("href", "/properties/p1/reports");
    // The orientation breadcrumb's "Properties" crumb links back to the list.
    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(
      within(breadcrumb).getByRole("link", { name: "Properties" }),
    ).toHaveAttribute("href", "/properties");
  });

  it("shows the Recent activity panel with a link to the filtered Activity page", async () => {
    const loadActivity = vi.fn(async () => ({
      events: [1, 2, 3].map(makeEvent),
      next_cursor: null,
    }));
    renderAt("p1", { loadActivity });
    const panel = await screen.findByRole("region", { name: "Recent activity" });
    expect(await within(panel).findByText("Added transaction 1")).toBeInTheDocument();
    expect(
      within(panel).getByRole("link", { name: "View all activity" }),
    ).toHaveAttribute("href", "/activity?property=p1");
    expect(loadActivity).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ limit: 5 }),
    );
  });
  it("shows an empty state in the Recent activity panel", async () => {
    renderAt("p1");
    const panel = await screen.findByRole("region", { name: "Recent activity" });
    expect(await within(panel).findByText("No activity yet")).toBeInTheDocument();
  });
  it("keeps the tiles usable when recent activity fails", async () => {
    renderAt("p1", {
      loadActivity: async () => {
        throw new ApiError(500, "Activity down", null);
      },
    });
    const panel = await screen.findByRole("region", { name: "Recent activity" });
    expect(await within(panel).findByRole("alert")).toBeInTheDocument();
    expect(
      within(panel).getByRole("button", { name: "Retry" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /income & expenses/i }),
    ).toBeInTheDocument();
  });
  it("shows the year-end checklist summary with a link per year", async () => {
    renderAt("p1");

    const section = await screen.findByRole("region", {
      name: "Year-end checklist",
    });
    expect(await within(section).findByText("3 need attention")).toBeInTheDocument();
    expect(
      within(section).getByText("3 need attention, 6 done, 2 not applicable"),
    ).toBeInTheDocument();
    expect(
      within(section).getByRole("link", { name: "Open 2024 checklist" }),
    ).toHaveAttribute("href", "/properties/p1/checklist?year=2024");
  });

  it("keeps the tiles usable when the checklist summary fails", async () => {
    renderAt("p1", {
      loadChecklistSummary: async () => {
        throw new ApiError(500, "Summary down", null);
      },
    });

    const section = await screen.findByRole("region", {
      name: "Year-end checklist",
    });
    expect(await within(section).findByRole("alert")).toBeInTheDocument();
    expect(
      within(section).getByRole("button", { name: "Retry" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /income & expenses/i }),
    ).toBeInTheDocument();
  });

  it("links the empty checklist state to Transactions", async () => {
    renderAt("p1", {
      loadChecklistSummary: async (id) => ({ property_id: id, years: [] }),
    });

    const section = await screen.findByRole("region", {
      name: "Year-end checklist",
    });
    expect(
      await within(section).findByRole("link", { name: "Go to Transactions" }),
    ).toHaveAttribute("href", "/properties/p1/transactions");
  });

  it("shows income, expenses and net from the report", async () => {
    renderAt("p1", { loadReport: async () => makeReport() });

    const tile = await screen.findByRole("region", {
      name: /income & expenses/i,
    });
    // Amounts now appear in both the numeric headline and the tile's chart data
    // table, so query for at least one occurrence within the tile.
    expect(within(tile).getAllByText("$24,000.00").length).toBeGreaterThan(0);
    expect(within(tile).getAllByText("$7,175.33").length).toBeGreaterThan(0);
    expect(within(tile).getAllByText("$16,824.67").length).toBeGreaterThan(0);
    expect(within(tile).getByText(/net income/i)).toBeInTheDocument();
  });

  it("shows the income/expenses/net chart once the report loads (Req 17.2)", async () => {
    renderAt("p1", { loadReport: async () => makeReport() });

    const tile = await screen.findByRole("region", {
      name: /income & expenses/i,
    });
    // The compact income/expenses/net chart region (role=img) lives inside the
    // tile, with its always-present data table alongside.
    expect(
      within(tile).getByRole("img", { name: /income, expenses, and net/i }),
    ).toBeInTheDocument();
    expect(within(tile).getByRole("table")).toBeInTheDocument();
  });

  it("labels a negative net as a loss", async () => {
    renderAt("p1", {
      loadReport: async () =>
        makeReport({
          totals: {
            total_income: "1000.00",
            total_expenses: "1500.00",
            net: "-500.00",
          },
        }),
    });

    const tile = await screen.findByRole("region", {
      name: /income & expenses/i,
    });
    expect(within(tile).getByText(/net loss/i)).toBeInTheDocument();
    // Appears in both the headline and the tile's chart data table.
    expect(within(tile).getAllByText("-$500.00").length).toBeGreaterThan(0);
  });

  it("shows the Line 18 depreciation total", async () => {
    renderAt("p1", { loadReport: async () => makeReport() });

    const tile = await screen.findByRole("region", { name: /depreciation/i });
    expect(within(tile).getByText("$5,833.33")).toBeInTheDocument();
  });

  it("shows zero depreciation when Line 18 is absent", async () => {
    renderAt("p1", {
      loadReport: async () =>
        makeReport({
          lines: [
            { line: 3, label: "Rents received", kind: "income", total: "10.00" },
          ],
        }),
    });

    const tile = await screen.findByRole("region", { name: /depreciation/i });
    expect(within(tile).getByText("$0.00")).toBeInTheDocument();
  });

  it("re-fetches the report when the tax year changes", async () => {
    const loadReport = vi
      .fn<(propertyId: string, taxYear: number) => Promise<ScheduleEReport>>()
      .mockResolvedValue(makeReport());
    renderAt("p1", { loadReport });

    await screen.findByText("1 Maple St, Springfield");
    await waitFor(() => expect(loadReport).toHaveBeenCalled());
    const initialCalls = loadReport.mock.calls.length;

    const currentYear = new Date().getFullYear();
    // The default selected year is the latest completed year (current - 1), so
    // pick a different year (current - 2) to actually trigger a re-fetch.
    const earlierYear = String(currentYear - 2);
    const user = userEvent.setup();
    await user.selectOptions(
      screen.getByLabelText(/tax year/i),
      earlierYear,
    );

    await waitFor(() =>
      expect(loadReport.mock.calls.length).toBeGreaterThan(initialCalls),
    );
    expect(loadReport).toHaveBeenCalledWith("p1", currentYear - 2);
  });

  it("loads and saves the property note", async () => {
    const loadNote = vi.fn().mockResolvedValue("Existing note");
    const saveNote = vi.fn().mockResolvedValue("Updated note");
    renderAt("p1", { loadNote, saveNote });

    const textarea = await screen.findByLabelText(/property note/i);
    await waitFor(() =>
      expect(textarea).toHaveValue("Existing note"),
    );

    const user = userEvent.setup();
    await user.clear(textarea);
    await user.type(textarea, "Updated note");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(saveNote).toHaveBeenCalledWith("p1", "Updated note"),
    );
    expect(await screen.findByText(/saved/i)).toBeInTheDocument();
  });

  it("renders stored property details when present", async () => {
    const withDetails: Property = {
      ...baseProperty,
      details: {
        year_built: 1973,
        features: { heating_type: "Forced Air" },
      },
    };
    renderAt("p1", { property: withDetails });

    expect(await screen.findByText(/forced air/i)).toBeInTheDocument();
  });

  it("shows a note when a property has no stored details", async () => {
    renderAt("p1");

    expect(
      await screen.findByText(/no additional property details are on file/i),
    ).toBeInTheDocument();
  });

  it("offers tax years back to the earliest asset's in-service year", async () => {
    const asset: DepreciableAsset = {
      id: "a1",
      description: "Building",
      cost_basis: "250000.00",
      placed_in_service_date: "2018-06-01",
      recovery_period_years: 27.5,
      created_at: "2018-06-01T00:00:00Z",
      updated_at: "2018-06-01T00:00:00Z",
    };
    renderAt("p1", { loadAssets: async () => [asset] });

    await screen.findByText("1 Maple St, Springfield");
    const select = screen.getByLabelText(/tax year/i);
    const currentYear = new Date().getFullYear();
    // The earliest asset year (2018) and the latest completed year (current - 1)
    // are both selectable; the current year is never offered (can't be filed).
    await screen.findByRole("option", { name: "2018" });
    expect(
      within(select).getByRole("option", { name: String(currentYear - 1) }),
    ).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "2018" })).toBeInTheDocument();
    expect(
      within(select).queryByRole("option", { name: String(currentYear) }),
    ).toBeNull();
  });

  it("shows the shared error affordance when the property fails to load", async () => {
    renderAt("missing", {
      property: async () => {
        throw new ApiError(404, "nope", null);
      },
    });

    // Identity errors now surface through the shared context as a single
    // consistent alert, while orientation (breadcrumb + tabs) persists.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not load this property/i,
    );
    expect(
      screen.getByRole("navigation", { name: "Breadcrumb" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Property sections" }),
    ).toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // Task 4.1 — overview orientation (Requirements 1.1, 1.2, 1.4, 2.4, 5.1)
  // ---------------------------------------------------------------------------

  it("ends the breadcrumb at the resolved name as a non-link current crumb (no trailing Overview)", async () => {
    renderAt("p1");

    await screen.findByText("1 Maple St, Springfield");

    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    // The ancestor crumb "Properties" is a link to the list.
    expect(
      within(breadcrumb).getByRole("link", { name: "Properties" }),
    ).toHaveAttribute("href", "/properties");
    // The property name is the current, NON-link tail crumb: it carries
    // aria-current="page" and is not rendered as a link.
    expect(
      within(breadcrumb).queryByRole("link", { name: "Maple Duplex" }),
    ).not.toBeInTheDocument();
    const current = within(breadcrumb).getByText("Maple Duplex");
    expect(current).toHaveAttribute("aria-current", "page");
    // There is no literal "Overview" crumb in the trail.
    expect(within(breadcrumb).queryByText("Overview")).not.toBeInTheDocument();
  });

  it("renders the four Section Tabs in order with Overview active on the index route", async () => {
    renderAt("p1");

    await screen.findByText("1 Maple St, Springfield");

    const tabs = screen.getByRole("navigation", { name: "Property sections" });
    const links = within(tabs).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Overview",
      "Transactions",
      "Repairs",
      "Depreciable Assets",
      "Loans",
      "Schedule E Report",
      "Checklist",
    ]);
    // The Overview tab is the active route on the property index and links to
    // the clean property base path.
    const overview = within(tabs).getByRole("link", { name: "Overview" });
    expect(overview).toHaveAttribute("href", "/properties/p1");
    expect(overview).toHaveAttribute("aria-current", "page");
    // No sibling sub-tab is active on the index route.
    expect(
      within(tabs).getByRole("link", { name: "Transactions" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("renders exactly one <h1> of 'Overview' with the resolved name as the subtitle, never the raw id", async () => {
    const { container } = renderAt("p1");

    await screen.findByText("1 Maple St, Springfield");

    // The page heading is the literal "Overview" (matching the sub-pages so the
    // header block height stays consistent across tabs).
    const headings = screen.getAllByRole("heading", { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent("Overview");
    // The resolved property name appears as the subtitle line (and breadcrumb
    // crumb), but never as a heading.
    expect(screen.getAllByText("Maple Duplex").length).toBeGreaterThanOrEqual(1);
    expect(
      screen.queryByRole("heading", { name: "Maple Duplex" }),
    ).not.toBeInTheDocument();
    // The machine id never leaks into user-facing text.
    expect(container).not.toHaveTextContent("p1");
  });

  // ---------------------------------------------------------------------------
  // Task 4.2 — identity from context, content seams, error (Req 3.1–3.3, 4.2–4.4)
  // ---------------------------------------------------------------------------

  it("shows the loading placeholder with breadcrumb + tabs and no tiles while the property loads", () => {
    // A never-resolving loader keeps the shared context in its `loading` state
    // so the orientation header renders with the placeholder name and no tiles.
    renderAt("p1", { property: () => new Promise<Property>(() => {}) });

    // The heading is the static "Overview"; the placeholder name shows as the
    // subtitle while the shared context is still loading.
    expect(
      screen.getByRole("heading", { name: "Overview" }),
    ).toBeInTheDocument();
    // The placeholder name shows in both the breadcrumb crumb and the subtitle.
    expect(
      screen.getAllByText("Loading property…").length,
    ).toBeGreaterThanOrEqual(2);
    expect(
      screen.getByRole("navigation", { name: "Breadcrumb" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Property sections" }),
    ).toBeInTheDocument();
    // No content tiles are rendered until the context is loaded.
    expect(
      screen.queryByRole("region", { name: /income & expenses/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: /quicklinks/i }),
    ).not.toBeInTheDocument();
  });

  it("shows the property name, breadcrumb + tabs, and tiles once loaded", async () => {
    renderAt("p1");

    // "Overview" is the heading; the property name is the subtitle below it.
    expect(
      await screen.findByRole("heading", { name: "Overview" }),
    ).toBeInTheDocument();
    await screen.findByText("1 Maple St, Springfield");
    expect(screen.getAllByText("Maple Duplex").length).toBeGreaterThanOrEqual(2);
    expect(
      screen.getByRole("navigation", { name: "Breadcrumb" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Property sections" }),
    ).toBeInTheDocument();
    // Loaded content tiles are present.
    expect(
      screen.getByRole("region", { name: /income & expenses/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /quicklinks/i }),
    ).toBeInTheDocument();
  });

  it("falls back to the neutral 'Property' name in the breadcrumb while in the error state", async () => {
    renderAt("missing", {
      property: async () => {
        throw new ApiError(404, "nope", null);
      },
    });

    await screen.findByRole("alert");
    // The resolved name falls back to the neutral "Property" placeholder; it is
    // the current (non-link) tail crumb and the heading's subtitle, while the
    // single <h1> stays the static "Overview".
    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    const current = within(breadcrumb).getByText("Property");
    expect(current).toHaveAttribute("aria-current", "page");
    expect(
      screen.getByRole("heading", { level: 1, name: "Overview" }),
    ).toBeInTheDocument();
  });

  it("still invokes the content seams (report, note, assets) for identity-from-context", async () => {
    const loadReport = vi.fn().mockResolvedValue(makeReport());
    const loadNote = vi.fn().mockResolvedValue("");
    const loadAssets = vi.fn().mockResolvedValue([]);
    renderAt("p1", { loadReport, loadNote, loadAssets });

    await screen.findByText("1 Maple St, Springfield");
    // Content fetches are retained and keyed off the context's propertyId;
    // identity itself comes from the shared context (no own getProperty seam).
    await waitFor(() => expect(loadReport).toHaveBeenCalledWith("p1", expect.any(Number)));
    await waitFor(() => expect(loadNote).toHaveBeenCalled());
    await waitFor(() => expect(loadAssets).toHaveBeenCalledWith("p1"));
  });

  // ---------------------------------------------------------------------------
  // Task 4.3 — accessibility (Requirements 5.1, 5.2, 5.5)
  // ---------------------------------------------------------------------------

  it("exposes the Breadcrumb and Property sections as distinct navigation landmarks", async () => {
    renderAt("p1");

    await screen.findByText("1 Maple St, Springfield");

    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    const tabs = screen.getByRole("navigation", { name: "Property sections" });
    expect(breadcrumb).toBeInTheDocument();
    expect(tabs).toBeInTheDocument();
    expect(breadcrumb).not.toBe(tabs);
  });

  it("has no axe violations in the loaded state", async () => {
    const { container } = renderAt("p1");

    await screen.findByText("1 Maple St, Springfield");

    // jsdom cannot compute rendered colors, so the color-contrast rule is not
    // machine-verifiable here — it stays a manual-AT check, as elsewhere.
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });

  it("has no axe violations in the error state", async () => {
    const { container } = renderAt("missing", {
      property: async () => {
        throw new ApiError(404, "nope", null);
      },
    });

    await screen.findByRole("alert");

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
