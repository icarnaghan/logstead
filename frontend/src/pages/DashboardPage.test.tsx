import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DashboardPage from "./DashboardPage";
import type { DashboardApi, DashboardSummary } from "../api/dashboard";
import type { CombinedScheduleEReport, ScheduleEReport } from "../api/reports";

const CURRENT_YEAR = new Date().getFullYear();

const POPULATED: DashboardSummary = {
  tax_year: CURRENT_YEAR,
  has_properties: true,
  total_income: "1500.00",
  total_expenses: "250.00",
  net: "1250.00",
  properties: [
    {
      property_id: "p1",
      property_name: "Maple Duplex",
      total_income: "1500.00",
      total_expenses: "250.00",
      net: "1250.00",
    },
    {
      property_id: "p2",
      property_name: "Oak Cottage",
      total_income: "0.00",
      total_expenses: "800.00",
      net: "-800.00",
    },
  ],
  empty_state_prompt: null,
};

const EMPTY: DashboardSummary = {
  tax_year: CURRENT_YEAR,
  has_properties: false,
  total_income: "0.00",
  total_expenses: "0.00",
  net: "0.00",
  properties: [],
  empty_state_prompt: "Add your first property to get started.",
};

function makePropertyReport(
  overrides: Partial<ScheduleEReport> = {},
): ScheduleEReport {
  return {
    header: {
      property_id: "p1",
      property_name: "Maple Duplex",
      address: "123 Maple St",
      property_type: "Multi-Family",
      tax_year: CURRENT_YEAR,
      fair_rental_days: 300,
      personal_use_days: 0,
    },
    lines: [
      { line: 3, label: "Rents received", kind: "income", total: "1500.00" },
      { line: 18, label: "Depreciation", kind: "expense", total: "1000.00" },
    ],
    other_items: [],
    totals: {
      total_income: "1500.00",
      total_expenses: "250.00",
      net: "1250.00",
    },
    ...overrides,
  };
}

const COMBINED: CombinedScheduleEReport = {
  tax_year: CURRENT_YEAR,
  properties: [
    makePropertyReport(),
    makePropertyReport({
      header: {
        property_id: "p2",
        property_name: "Oak Cottage",
        address: "45 Oak Ln",
        property_type: null,
        tax_year: CURRENT_YEAR,
        fair_rental_days: 0,
        personal_use_days: 0,
      },
      lines: [
        { line: 18, label: "Depreciation", kind: "expense", total: "834.50" },
      ],
      totals: {
        total_income: "0.00",
        total_expenses: "800.00",
        net: "-800.00",
      },
    }),
  ],
  totals: {
    total_income: "1500.00",
    total_expenses: "1050.00",
    net: "450.00",
  },
};

function makeApi(overrides: Partial<DashboardApi> = {}): DashboardApi {
  return {
    getDashboard: vi.fn().mockResolvedValue(POPULATED),
    getPropertySummaries: vi.fn().mockResolvedValue(POPULATED.properties),
    ...overrides,
  } as unknown as DashboardApi;
}

function renderPage(
  api: DashboardApi,
  loadCombined: (year: number) => Promise<CombinedScheduleEReport> = vi
    .fn()
    .mockResolvedValue(COMBINED),
  loadAssets: (propertyId: string) => Promise<
    import("../api/assets").DepreciableAsset[]
  > = async () => [],
) {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <DashboardPage
        api={api}
        loadCombined={loadCombined}
        loadAssets={loadAssets}
      />
    </MemoryRouter>,
  );
}

describe("DashboardPage — portfolio snapshot (Req 11.1)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders total income, expenses, and net income", async () => {
    renderPage(makeApi());

    const totals = await screen.findByRole("region", {
      name: new RegExp(`Portfolio totals for ${CURRENT_YEAR}`),
    });
    expect(within(totals).getByText("$1,500.00")).toBeInTheDocument();
    expect(within(totals).getByText("$250.00")).toBeInTheDocument();
    expect(within(totals).getByText("$1,250.00")).toBeInTheDocument();
    expect(within(totals).getByText(/net income/i)).toBeInTheDocument();
  });

  it("defaults to the current tax year on first load", async () => {
    const api = makeApi();
    renderPage(api);

    await screen.findByRole("region", { name: /portfolio totals/i });
    expect(api.getDashboard).toHaveBeenCalledWith(
      CURRENT_YEAR,
      expect.anything(),
    );
  });

  it("shows a negative net clearly as a loss", async () => {
    const api = makeApi({
      getDashboard: vi.fn().mockResolvedValue({
        ...POPULATED,
        total_income: "100.00",
        total_expenses: "900.00",
        net: "-800.00",
      }),
    });
    renderPage(api);

    const totals = await screen.findByRole("region", {
      name: /portfolio totals/i,
    });
    expect(within(totals).getByText(/net loss/i)).toBeInTheDocument();
    expect(within(totals).getByText("-$800.00")).toBeInTheDocument();
  });
});

describe("DashboardPage — combined Schedule E + depreciation", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows combined totals and summed Line 18 depreciation", async () => {
    const loadCombined = vi.fn().mockResolvedValue(COMBINED);
    renderPage(makeApi(), loadCombined);

    const combined = await screen.findByRole("region", {
      name: /combined schedule e/i,
    });
    // 1000.00 + 834.50 = 1834.50 (exact, no float error).
    expect(within(combined).getByText("$1,834.50")).toBeInTheDocument();
    expect(within(combined).getByText("$1,050.00")).toBeInTheDocument();

    const depreciation = screen.getByRole("region", {
      name: /depreciation in service/i,
    });
    expect(
      within(depreciation).getByText("$1,834.50"),
    ).toBeInTheDocument();
    // Both properties have non-zero Line 18.
    expect(
      within(depreciation).getByText(/2 properties with depreciation/i),
    ).toBeInTheDocument();
  });

  it("loads the combined report for the current year", async () => {
    const loadCombined = vi.fn().mockResolvedValue(COMBINED);
    renderPage(makeApi(), loadCombined);

    await screen.findByRole("region", { name: /combined schedule e/i });
    expect(loadCombined).toHaveBeenCalledWith(CURRENT_YEAR);
  });
});

describe("DashboardPage — needs attention", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists a $0-income property with a link to it", async () => {
    renderPage(makeApi());

    const attention = await screen.findByRole("region", {
      name: /needs attention/i,
    });
    const oak = within(attention).getByRole("link", { name: "Oak Cottage" });
    expect(oak).toHaveAttribute("href", "/properties/p2");
    // The property with income is not flagged.
    expect(
      within(attention).queryByRole("link", { name: "Maple Duplex" }),
    ).not.toBeInTheDocument();
  });

  it("shows a positive message when all properties have income", async () => {
    const api = makeApi({
      getDashboard: vi.fn().mockResolvedValue({
        ...POPULATED,
        properties: [POPULATED.properties[0]],
      }),
    });
    renderPage(api);

    const attention = await screen.findByRole("region", {
      name: /needs attention/i,
    });
    expect(
      within(attention).getByText(/all properties have recorded income/i),
    ).toBeInTheDocument();
  });
});

describe("DashboardPage — properties launchpad (Req 11.2)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists each property with a link and its net", async () => {
    renderPage(makeApi());

    const launchpad = await screen.findByRole("region", {
      name: /^properties$/i,
    });
    const maple = within(launchpad).getByRole("link", { name: "Maple Duplex" });
    expect(maple).toHaveAttribute("href", "/properties/p1");
    const oak = within(launchpad).getByRole("link", { name: "Oak Cottage" });
    expect(oak).toHaveAttribute("href", "/properties/p2");
    expect(within(launchpad).getByText("$1,250.00")).toBeInTheDocument();
    expect(within(launchpad).getByText("-$800.00")).toBeInTheDocument();
  });
});

describe("DashboardPage — quick actions", () => {
  beforeEach(() => vi.clearAllMocks());

  it("links only to real routes", async () => {
    renderPage(makeApi());

    const actions = await screen.findByRole("region", {
      name: /quick actions/i,
    });
    const addProperty = within(actions).getByRole("link", {
      name: /add property/i,
    });
    expect(addProperty).toHaveAttribute("href", "/properties");
  });
});

describe("DashboardPage — year selector (Req 11.3)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("re-fetches the dashboard and combined report for the selected year", async () => {
    const user = userEvent.setup();
    const getDashboard = vi.fn().mockResolvedValue(POPULATED);
    const loadCombined = vi.fn().mockResolvedValue(COMBINED);
    const api = makeApi({ getDashboard });
    renderPage(api, loadCombined);

    await screen.findByRole("region", { name: /portfolio totals/i });
    expect(getDashboard).toHaveBeenCalledWith(CURRENT_YEAR, expect.anything());
    expect(loadCombined).toHaveBeenCalledWith(CURRENT_YEAR);

    const priorYear = CURRENT_YEAR - 1;
    await user.selectOptions(
      screen.getByLabelText(/tax year/i),
      String(priorYear),
    );

    await waitFor(() =>
      expect(getDashboard).toHaveBeenCalledWith(priorYear, expect.anything()),
    );
    await waitFor(() =>
      expect(loadCombined).toHaveBeenCalledWith(priorYear),
    );
  });

  it("offers tax years back to the earliest in-service year across properties", async () => {
    const asset = (year: string) => ({
      id: `a-${year}`,
      description: "Building",
      cost_basis: "250000.00",
      placed_in_service_date: `${year}-06-01`,
      recovery_period_years: 27.5,
      created_at: `${year}-06-01T00:00:00Z`,
      updated_at: `${year}-06-01T00:00:00Z`,
    });
    // p1 placed in service 2017, p2 in 2020 → earliest across portfolio is 2017.
    const loadAssets = vi.fn(async (id: string) =>
      id === "p1" ? [asset("2017")] : [asset("2020")],
    );
    renderPage(makeApi(), vi.fn().mockResolvedValue(COMBINED), loadAssets);

    await screen.findByRole("region", { name: /portfolio totals/i });
    const select = await screen.findByLabelText(/tax year/i);
    // The earliest year (2017) becomes selectable, alongside the current year.
    await within(select).findByRole("option", { name: "2017" });
    expect(
      within(select).getByRole("option", { name: String(CURRENT_YEAR) }),
    ).toBeInTheDocument();
  });
});

describe("DashboardPage — empty state (Req 11.4)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the add-first-property prompt when there are no properties", async () => {
    const api = makeApi({
      getDashboard: vi.fn().mockResolvedValue(EMPTY),
    });
    renderPage(api);

    expect(
      await screen.findByText(/add your first property to get started/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /add your first property/i }),
    ).toHaveAttribute("href", "/properties");
    // No portfolio tiles are rendered in the empty state.
    expect(
      screen.queryByRole("region", { name: /portfolio totals/i }),
    ).not.toBeInTheDocument();
  });
});

describe("DashboardPage — numbers-first, no charts", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders no chart/canvas/svg elements", async () => {
    const { container } = renderPage(makeApi());

    await screen.findByRole("region", { name: /portfolio totals/i });

    expect(container.querySelector("canvas")).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
  });
});

describe("DashboardPage — accessibility (Req 14.4)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("has no detectable axe violations", async () => {
    const { container } = renderPage(makeApi());

    await screen.findByRole("region", { name: /portfolio totals/i });

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
