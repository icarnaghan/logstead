import { render, screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { ChartCard } from "./ChartCard";
import DepreciationTrendChart, {
  DepreciationTrendTable,
} from "./DepreciationTrendChart";
import { depreciationTrend, type DepreciationTrendDatum } from "./prepare";
import type { TrendsSeries } from "../../api/dashboard";
import { ThemeProvider } from "../../theme/ThemeProvider";

/**
 * Component tests for the portfolio depreciation (Schedule E Line 18) **trend**
 * chart + its always-present data table (task 7.4, Requirements 5.1, 5.3, 10.1,
 * 10.4).
 *
 * Mirrors `DepreciationChart.test.tsx`: the chart is rendered NON-lazily inside
 * a `ChartCard` so we assert the accessibility contract (`role="img"` +
 * `aria-label`) and the data-table contract (one row per Data_Year ascending,
 * formatted amounts, empty-state note) without Suspense timing. `ResizeObserver`
 * is stubbed globally in `src/test/setup.ts`, and `useChartColors` subscribes to
 * the theme so the chart is wrapped in a `ThemeProvider`.
 */

const SERIES: TrendsSeries = {
  years: [
    {
      tax_year: 2023,
      total_income: "0.00",
      total_expenses: "0.00",
      net: "0.00",
      depreciation_total: "5833.33",
      properties: [],
    },
    {
      tax_year: 2024,
      total_income: "0.00",
      total_expenses: "0.00",
      net: "0.00",
      depreciation_total: "10000.00",
      properties: [],
    },
  ],
};

const DATA: DepreciationTrendDatum[] = depreciationTrend(SERIES);

function renderCard(data: DepreciationTrendDatum[] = DATA) {
  return render(
    <ThemeProvider>
      <ChartCard
        title="Depreciation over time"
        ariaLabel="Portfolio depreciation total by year"
        height={220}
        chart={<DepreciationTrendChart data={data} />}
        dataTable={<DepreciationTrendTable data={data} />}
      />
    </ThemeProvider>,
  );
}

describe("DepreciationTrendChart — accessibility contract (Req 10.1)", () => {
  it("renders a role=img chart region with a non-empty aria-label", () => {
    renderCard();
    const region = screen.getByRole("img");
    expect(
      (region.getAttribute("aria-label") ?? "").trim().length,
    ).toBeGreaterThan(0);
  });

  it("re-exports its always-present table from the chart module", () => {
    expect(DepreciationTrendTable).toBeTypeOf("function");
  });
});

describe("DepreciationTrendTable — always-present data table (Req 5.1, 5.3)", () => {
  it("renders one row per Data_Year ascending with formatted amounts", () => {
    render(<DepreciationTrendTable data={DATA} />);
    const table = screen.getByRole("table");
    const bodyRows = within(table).getAllByRole("row").slice(1); // drop header
    expect(bodyRows).toHaveLength(SERIES.years.length);

    const years = within(table)
      .getAllByRole("rowheader")
      .map((cell) => cell.textContent);
    expect(years).toEqual(["2023", "2024"]);

    expect(within(table).getByText("$5,833.33")).toBeInTheDocument();
    expect(within(table).getByText("$10,000.00")).toBeInTheDocument();
  });

  it("shows an empty-state note when there is no depreciation data", () => {
    render(<DepreciationTrendTable data={[]} />);
    expect(
      screen.getByText(/no depreciation to show/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("DepreciationTrendChart — accessibility (axe)", () => {
  it("has no automatically detectable a11y violations", async () => {
    const { container } = renderCard();
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
