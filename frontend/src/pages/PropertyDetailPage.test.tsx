import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import PropertyDetailPage from "./PropertyDetailPage";
import { ApiError, type Property } from "../api/properties";
import type { ScheduleEReport } from "../api/reports";
import type { DepreciableAsset } from "../api/assets";

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
    ...overrides,
  };
}

interface RenderOptions {
  property?: Property | (() => Promise<Property>);
  loadReport?: (propertyId: string, taxYear: number) => Promise<ScheduleEReport>;
  loadNote?: (propertyId: string) => Promise<string>;
  saveNote?: (propertyId: string, text: string) => Promise<string>;
  loadAssets?: (propertyId: string) => Promise<DepreciableAsset[]>;
}

function renderAt(id: string, options: RenderOptions = {}) {
  const propertyOption = options.property;
  const load: () => Promise<Property> =
    typeof propertyOption === "function"
      ? propertyOption
      : async () => propertyOption ?? baseProperty;
  render(
    <MemoryRouter initialEntries={[`/properties/${id}`]}>
      <Routes>
        <Route
          path="/properties/:propertyId"
          element={
            <PropertyDetailPage
              load={load}
              loadReport={options.loadReport ?? (async () => makeReport())}
              loadPhotos={async () => []}
              loadAssets={options.loadAssets ?? (async () => [])}
              loadNote={options.loadNote ?? (async () => "")}
              saveNote={options.saveNote ?? (async (_id, text) => text)}
            />
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("PropertyDetailPage dashboard", () => {
  it("renders the property header and quicklinks", async () => {
    renderAt("p1");

    expect(
      await screen.findByRole("heading", { name: "Maple Duplex" }),
    ).toBeInTheDocument();
    expect(screen.getByText("1 Maple St, Springfield")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /^transactions$/i }),
    ).toHaveAttribute("href", "/properties/p1/transactions");
    expect(
      screen.getByRole("link", { name: /depreciable assets/i }),
    ).toHaveAttribute("href", "/properties/p1/assets");
    expect(
      screen.getByRole("link", { name: /schedule e report/i }),
    ).toHaveAttribute("href", "/properties/p1/reports");
    expect(screen.getByRole("link", { name: /all properties/i })).toBeInTheDocument();
  });

  it("shows income, expenses and net from the report", async () => {
    renderAt("p1", { loadReport: async () => makeReport() });

    const tile = await screen.findByRole("region", {
      name: /income & expenses/i,
    });
    expect(within(tile).getByText("$24,000.00")).toBeInTheDocument();
    expect(within(tile).getByText("$7,175.33")).toBeInTheDocument();
    expect(within(tile).getByText("$16,824.67")).toBeInTheDocument();
    expect(within(tile).getByText(/net income/i)).toBeInTheDocument();
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
    expect(within(tile).getByText("-$500.00")).toBeInTheDocument();
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

    await screen.findByRole("heading", { name: "Maple Duplex" });
    await waitFor(() => expect(loadReport).toHaveBeenCalled());
    const initialCalls = loadReport.mock.calls.length;

    const currentYear = new Date().getFullYear();
    const priorYear = String(currentYear - 1);
    const user = userEvent.setup();
    await user.selectOptions(
      screen.getByLabelText(/tax year/i),
      priorYear,
    );

    await waitFor(() =>
      expect(loadReport.mock.calls.length).toBeGreaterThan(initialCalls),
    );
    expect(loadReport).toHaveBeenCalledWith("p1", currentYear - 1);
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

    await screen.findByRole("heading", { name: "Maple Duplex" });
    const select = screen.getByLabelText(/tax year/i);
    const currentYear = new Date().getFullYear();
    // The earliest asset year (2018) and the current year are both selectable.
    await screen.findByRole("option", { name: "2018" });
    expect(
      within(select).getByRole("option", { name: String(currentYear) }),
    ).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "2018" })).toBeInTheDocument();
  });

  it("shows a not-found message on 404", async () => {
    renderAt("missing", {
      property: async () => {
        throw new ApiError(404, "nope", null);
      },
    });

    expect(await screen.findByText(/could not be found/i)).toBeInTheDocument();
  });
});
