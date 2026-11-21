import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DashboardPage from "./DashboardPage";
import type { DashboardApi, DashboardSummary, TrendsSeries } from "../api/dashboard";
import { ThemeProvider } from "../theme/ThemeProvider";

// The Year-end checklist card loads on its own; an empty portfolio omits it so
// these tests stay about the existing dashboard content.
vi.mock("../api/yearEndChecklist", () => ({
  yearEndChecklistApi: {
    getPortfolioSummary: () => Promise.resolve({ tax_year: 2024, properties: [] }),
  },
}));

/**
 * Error-boundary + code-splitting behavior for DashboardPage (task 9.4).
 *
 * This file lives apart from `DashboardPage.test.tsx` because it `vi.mock`s one
 * lazy chart module to throw on render. `vi.mock` is hoisted and file-scoped, so
 * isolating it here keeps the module mock from leaking into the broader page
 * tests. The page wires each trend chart through `LazyChart`
 * (`ChartErrorBoundary` → `Suspense` → lazy Recharts chart) with the Recharts-
 * free data table as the fallback; when a chart throws, its boundary must show
 * that table plus a visible notice while the rest of the page stays usable
 * (Requirement 10.3, 10.5).
 */

// Force the income/expenses/net trend CHART to throw on render. The default
// export is what `React.lazy(() => import(...))` resolves to inside the page.
// The Recharts-free table re-export is preserved so the eager ChartCard
// dataTable and the LazyChart fallbackTable both still render real content.
vi.mock("../components/charts/IncomeExpenseNetTrendChart", async () => {
  const actual = await vi.importActual<
    typeof import("../components/charts/IncomeExpenseNetTrendChart")
  >("../components/charts/IncomeExpenseNetTrendChart");
  return {
    ...actual,
    default: function ThrowingChart(): never {
      throw new Error("chart chunk failed to render");
    },
  };
});

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
  ],
  empty_state_prompt: null,
};

const TRENDS: TrendsSeries = {
  years: [
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
      ],
    },
  ],
};

function makeApi(): DashboardApi {
  return {
    getDashboard: vi.fn().mockResolvedValue(POPULATED),
    getPropertySummaries: vi.fn().mockResolvedValue(POPULATED.properties),
    getTrends: vi.fn().mockResolvedValue(TRENDS),
  } as unknown as DashboardApi;
}

function renderPage(api: DashboardApi) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={["/"]}>
        <DashboardPage api={api} />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("DashboardPage — chart error boundary & code-splitting (Req 10.3, 10.5)", () => {
  // Silence the expected React error-boundary console noise for the throw.
  let consoleError: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    vi.clearAllMocks();
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    consoleError.mockRestore();
  });

  it("falls back to the data table when a lazy chart throws, keeping the rest of the page usable", async () => {
    renderPage(makeApi());

    // The failing chart's ChartErrorBoundary renders the always-present data
    // table as its fallback, so the income/expenses/net figures survive the
    // chart failure. The caption identifies that table.
    const ienCaption = await screen.findByText(
      /portfolio income, expenses, and net for every year with data/i,
    );
    const ienTable = ienCaption.closest("table");
    expect(ienTable).not.toBeNull();
    expect(ienTable).toHaveTextContent("$450.00");

    // The rest of the page stays usable: the headline and the other two trend
    // charts' tables are still present, and the navigation tiles still render.
    expect(
      screen.getByRole("region", {
        name: new RegExp(`portfolio net for ${CURRENT_YEAR}`, "i"),
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/net contribution per property for each year/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/portfolio depreciation total .* by year/i),
    ).toBeInTheDocument();

    const launchpad = screen.getByRole("region", { name: /properties/i });
    expect(
      within(launchpad).getByRole("link", { name: /maple duplex/i }),
    ).toHaveAttribute("href", "/properties/p1");

    // The failure is not surfaced as a page-level error.
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });
});
