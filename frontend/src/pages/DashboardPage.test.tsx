import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DashboardPage from "./DashboardPage";
import type {
  DashboardApi,
  DashboardSummary,
  TrendsSeries,
} from "../api/dashboard";
import { ThemeProvider } from "../theme/ThemeProvider";

// The Year-end checklist card loads on its own; an empty portfolio omits it so
// these tests stay about the existing dashboard content.
vi.mock("../api/yearEndChecklist", () => ({
  yearEndChecklistApi: {
    getPortfolioSummary: () => Promise.resolve({ tax_year: 2024, properties: [] }),
  },
}));

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

/**
 * A two-year trends series. The Latest_Data_Year (last entry) is the one the
 * retained tiles derive from: Maple Duplex nets +1250.00 with recorded income,
 * Oak Cottage nets -800.00 with "0.00" income (so it is the needs-attention
 * nudge), and the portfolio depreciation total for the year is non-zero.
 */
const TRENDS: TrendsSeries = {
  years: [
    {
      tax_year: CURRENT_YEAR - 1,
      total_income: "1000.00",
      total_expenses: "200.00",
      net: "800.00",
      depreciation_total: "500.00",
      properties: [
        {
          property_id: "p1",
          property_name: "Maple Duplex",
          total_income: "1000.00",
          total_expenses: "200.00",
          net: "800.00",
        },
        {
          property_id: "p2",
          property_name: "Oak Cottage",
          total_income: "0.00",
          total_expenses: "0.00",
          net: "0.00",
        },
      ],
    },
    {
      tax_year: CURRENT_YEAR,
      total_income: "1500.00",
      total_expenses: "1050.00",
      net: "450.00",
      depreciation_total: "1834.50",
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
    },
  ],
};

const NO_DATA: TrendsSeries = { years: [] };

function makeApi(overrides: Partial<DashboardApi> = {}): DashboardApi {
  return {
    getDashboard: vi.fn().mockResolvedValue(POPULATED),
    getPropertySummaries: vi.fn().mockResolvedValue(POPULATED.properties),
    getTrends: vi.fn().mockResolvedValue(TRENDS),
    ...overrides,
  } as unknown as DashboardApi;
}

function renderPage(api: DashboardApi) {
  return render(
    // The dashboard renders charts, which read `useChartColors → useTheme`;
    // without a ThemeProvider that hook throws, so every render is wrapped here.
    <ThemeProvider>
      <MemoryRouter initialEntries={["/"]}>
        <DashboardPage api={api} />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("DashboardPage — Latest_Data_Year headline (Req 1)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the latest-year net labeled with the four-digit year", async () => {
    renderPage(makeApi());

    const headline = await screen.findByRole("region", {
      name: new RegExp(`portfolio net for ${CURRENT_YEAR}`, "i"),
    });
    expect(headline).toHaveTextContent(String(CURRENT_YEAR));
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.3
    // The dashboard net headline rounds to whole dollars: "450.00" → "$450".
    expect(headline).toHaveTextContent("$450");
  });
});

describe("DashboardPage — Depreciation_Summary_Tile (Req 12)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the Latest_Data_Year depreciation_total and non-zero property count", async () => {
    renderPage(makeApi());

    const tile = await screen.findByRole("region", {
      name: /depreciation in service/i,
    });
    // Reconciles with the last TrendYear's depreciation_total.
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.3
    // The depreciation tile rounds half-up by magnitude: "1834.50" → "$1,835".
    expect(tile).toHaveTextContent("$1,835");
    // Both properties carry recorded data in the latest year.
    expect(tile).toHaveTextContent(/2 properties with depreciation/i);
  });

  it("reports zero properties when the Latest_Data_Year depreciation is 0.00", async () => {
    const zeroDep: TrendsSeries = {
      years: [
        {
          ...TRENDS.years[1],
          depreciation_total: "0.00",
        },
      ],
    };
    renderPage(makeApi({ getTrends: vi.fn().mockResolvedValue(zeroDep) }));

    const tile = await screen.findByRole("region", {
      name: /depreciation in service/i,
    });
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.3
    // "0.00" rounds to "$0" on the whole-dollar depreciation tile.
    expect(tile).toHaveTextContent("$0");
    expect(tile).toHaveTextContent(/0 properties with depreciation/i);
  });
});

describe("DashboardPage — Needs_Attention_Nudge (Req 9.5, 9.6)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("links each zero-income property to its detail page", async () => {
    renderPage(makeApi());

    const tile = await screen.findByRole("region", {
      name: /needs attention/i,
    });
    const link = within(tile).getByRole("link", { name: /oak cottage/i });
    expect(link).toHaveAttribute("href", "/properties/p2");
    // Maple Duplex has income, so it is not nudged.
    expect(within(tile).queryByText(/maple duplex/i)).toBeNull();
  });

  it("shows a positive confirmation when every property has income", async () => {
    const allIncome: TrendsSeries = {
      years: [
        {
          ...TRENDS.years[1],
          properties: TRENDS.years[1].properties.map((p) => ({
            ...p,
            total_income: "1000.00",
          })),
        },
      ],
    };
    renderPage(makeApi({ getTrends: vi.fn().mockResolvedValue(allIncome) }));

    const tile = await screen.findByRole("region", {
      name: /needs attention/i,
    });
    expect(tile).toHaveTextContent(/all properties have recorded income/i);
  });
});

describe("DashboardPage — Properties_Launchpad (Req 9.5, 9.6)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders one detail-page link per property annotated with its net", async () => {
    renderPage(makeApi());

    const tile = await screen.findByRole("region", { name: /properties/i });
    const maple = within(tile).getByRole("link", { name: /maple duplex/i });
    expect(maple).toHaveAttribute("href", "/properties/p1");
    const oak = within(tile).getByRole("link", { name: /oak cottage/i });
    expect(oak).toHaveAttribute("href", "/properties/p2");
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.4
    // Per-property net rounds to whole dollars: "1250.00" → "$1,250",
    // "-800.00" → "-$800" (magnitude rounded, sign preserved).
    expect(tile).toHaveTextContent("$1,250");
    expect(tile).toHaveTextContent("-$800");
  });
});

describe("DashboardPage — empty & no-data states (Req 8)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows only the add-first-property empty state for zero properties", async () => {
    renderPage(
      makeApi({
        getDashboard: vi.fn().mockResolvedValue(EMPTY),
        getTrends: vi.fn().mockResolvedValue(NO_DATA),
      }),
    );

    expect(
      await screen.findByText("Add your first property to get started."),
    ).toBeInTheDocument();
    // No headline, no tiles.
    expect(
      screen.queryByRole("region", { name: /portfolio net/i }),
    ).toBeNull();
    expect(
      screen.queryByRole("region", { name: /depreciation in service/i }),
    ).toBeNull();
  });

  it("shows a calm no-data indication (not an error) for properties but zero Data_Years", async () => {
    renderPage(
      makeApi({ getTrends: vi.fn().mockResolvedValue(NO_DATA) }),
    );

    await waitFor(() =>
      expect(screen.getByText(/no data yet/i)).toBeInTheDocument(),
    );
    // Not an error.
    expect(screen.queryByRole("alert")).toBeNull();
    // No headline, no charts, no tiles.
    expect(screen.queryByRole("region", { name: /portfolio net/i })).toBeNull();
    expect(
      screen.queryByRole("region", { name: /depreciation in service/i }),
    ).toBeNull();
  });
});

describe("DashboardPage — loading state", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a loading status, not the no-data message, while the trends are still pending", async () => {
    // The summary resolves first; the trends never do within this test.
    renderPage(
      makeApi({ getTrends: vi.fn().mockReturnValue(new Promise(() => {})) }),
    );

    expect(
      await screen.findByRole("status", { name: /loading dashboard/i }),
    ).toBeInTheDocument();
    // Give the resolved summary a chance to render before asserting absence.
    await waitFor(() =>
      expect(
        screen.getByRole("status", { name: /loading dashboard/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText(/no data yet/i)).toBeNull();
  });

  it("shows a loading status before anything has resolved", () => {
    renderPage(
      makeApi({
        getDashboard: vi.fn().mockReturnValue(new Promise(() => {})),
        getTrends: vi.fn().mockReturnValue(new Promise(() => {})),
      }),
    );

    expect(
      screen.getByRole("status", { name: /loading dashboard/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/no data yet/i)).toBeNull();
  });

  it("replaces the loading status with the error when a load fails", async () => {
    renderPage(
      makeApi({ getTrends: vi.fn().mockRejectedValue(new Error("boom")) }),
    );

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: /loading dashboard/i })).toBeNull();
  });
});

describe("DashboardPage — error handling", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows an error indication when the trends fetch fails", async () => {
    renderPage(
      makeApi({ getTrends: vi.fn().mockRejectedValue(new Error("boom")) }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not load the dashboard/i,
    );
    // An error suppresses the headline, charts, and tiles — no partial render.
    expect(screen.queryByRole("region", { name: /portfolio net/i })).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
  });
});

describe("DashboardPage — Latest_Data_Year headline loss styling (Req 1)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("styles a negative latest-year net as a loss with a textual cue", async () => {
    // A latest year whose portfolio net is negative — the headline must carry
    // the danger token AND a textual "Loss" cue so meaning never rests on color.
    const lossSeries: TrendsSeries = {
      years: [
        {
          ...TRENDS.years[1],
          total_income: "100.00",
          total_expenses: "900.00",
          net: "-800.00",
        },
      ],
    };
    renderPage(makeApi({ getTrends: vi.fn().mockResolvedValue(lossSeries) }));

    const headline = await screen.findByRole("region", {
      name: new RegExp(`portfolio net for ${CURRENT_YEAR}`, "i"),
    });
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.3
    // The negative headline rounds the magnitude and keeps the sign:
    // "-800.00" → "-$800". The textual loss cues below stay unchanged.
    expect(headline).toHaveTextContent("-$800");
    // Heading announces a net loss (not net income).
    expect(headline).toHaveTextContent(/net loss/i);
    // Textual loss cue present and styled with the danger token.
    const cue = within(headline).getByText("Loss");
    expect(cue).toHaveClass("text-danger");
  });

  it("styles a non-negative latest-year net as income with no loss cue", async () => {
    renderPage(makeApi());

    const headline = await screen.findByRole("region", {
      name: new RegExp(`portfolio net for ${CURRENT_YEAR}`, "i"),
    });
    expect(headline).toHaveTextContent(/net income/i);
    expect(within(headline).queryByText("Loss")).toBeNull();
    // The positive figure is styled with the success token.
    const figure = headline.querySelector(".tabular-nums");
    expect(figure).toHaveClass("text-success");
  });
});

describe("DashboardPage — code-splitting & always-present data tables (Req 10)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders all three trend charts inside a ChartCard with an accessible label", async () => {
    renderPage(makeApi());

    // Each chart's visual region carries role="img" + a summarizing aria-label
    // (ChartCard contract). All three must be present for the latest-year view.
    expect(
      await screen.findByRole("img", {
        name: /income, expenses, and net for every year/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: /net contribution per property for every year/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: /portfolio depreciation .* for every year/i,
      }),
    ).toBeInTheDocument();
  });

  it("renders every chart's data table in the DOM on first paint, before the lazy chart resolves", async () => {
    renderPage(makeApi());

    // The tables are passed as ChartCard.dataTable — a Recharts-free module
    // imported eagerly — so they are present synchronously, without awaiting
    // the lazy Recharts chunk. Wait only for the trends-dependent first paint.
    await screen.findByRole("region", {
      name: new RegExp(`portfolio net for ${CURRENT_YEAR}`, "i"),
    });

    // Income/expenses/net trend table: one row per Data_Year, ascending.
    const ienCaption = screen.getByText(
      /portfolio income, expenses, and net for every year with data/i,
    );
    const ienTable = ienCaption.closest("table");
    expect(ienTable).not.toBeNull();
    const ienRowHeaders = within(ienTable as HTMLElement)
      .getAllByRole("rowheader")
      .map((cell) => cell.textContent);
    expect(ienRowHeaders).toEqual([
      String(CURRENT_YEAR - 1),
      String(CURRENT_YEAR),
    ]);
    // Latest year's figures are present in the table (not only the chart).
    expect(ienTable).toHaveTextContent("$1,500.00");
    expect(ienTable).toHaveTextContent("$450.00");

    // Net-by-property trend table: one row per Data_Year, a column per property.
    const netCaption = screen.getByText(
      /net contribution per property for each year/i,
    );
    const netTable = netCaption.closest("table");
    expect(netTable).not.toBeNull();
    expect(
      within(netTable as HTMLElement).getByRole("columnheader", {
        name: /maple duplex/i,
      }),
    ).toBeInTheDocument();
    expect(
      within(netTable as HTMLElement).getByRole("columnheader", {
        name: /oak cottage/i,
      }),
    ).toBeInTheDocument();

    // Depreciation trend table: one row per Data_Year with the Line 18 total.
    const depCaption = screen.getByText(
      /portfolio depreciation total .* by year/i,
    );
    const depTable = depCaption.closest("table");
    expect(depTable).not.toBeNull();
    expect(depTable).toHaveTextContent("$500.00");
    expect(depTable).toHaveTextContent("$1,834.50");
  });
});
