import { render, screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { ChartCard } from "./ChartCard";
import IncomeExpenseNetTrendChart, {
  IncomeExpenseNetTrendTable,
} from "./IncomeExpenseNetTrendChart";
import { incomeExpenseNetTrend, type TrendPointDatum } from "./prepare";
import type { TrendsSeries } from "../../api/dashboard";
import { ThemeProvider } from "../../theme/ThemeProvider";

/**
 * Component tests for the portfolio income / expenses / net **trend** chart +
 * its always-present data table (task 7.4, Requirements 3.1, 3.3, 3.4, 10.1,
 * 10.4).
 *
 * Mirrors `IncomeExpenseNetChart.test.tsx`: the chart is rendered NON-lazily
 * (imported directly) inside a `ChartCard` so we assert the accessibility
 * contract (`role="img"` + `aria-label`) and the data-table contract (one row
 * per Data_Year ascending, formatted amounts, textual loss cue) without
 * Suspense timing. `ResizeObserver` is stubbed globally in `src/test/setup.ts`,
 * and `useChartColors` subscribes to the theme so the chart is wrapped in a
 * `ThemeProvider`.
 */

// Deliberately ascending years with a loss year (2023) and a gain year (2024).
const SERIES: TrendsSeries = {
  years: [
    {
      tax_year: 2023,
      total_income: "100.00",
      total_expenses: "900.00",
      net: "-800.00",
      depreciation_total: "0.00",
      properties: [],
    },
    {
      tax_year: 2024,
      total_income: "1500.00",
      total_expenses: "250.00",
      net: "1250.00",
      depreciation_total: "0.00",
      properties: [],
    },
  ],
};

const DATA: TrendPointDatum[] = incomeExpenseNetTrend(SERIES);

function renderCard(data: TrendPointDatum[] = DATA) {
  return render(
    <ThemeProvider>
      <ChartCard
        title="Income, expenses & net over time"
        ariaLabel="Portfolio income, expenses, and net for every year with data"
        height={220}
        chart={<IncomeExpenseNetTrendChart data={data} />}
        dataTable={<IncomeExpenseNetTrendTable data={data} />}
      />
    </ThemeProvider>,
  );
}

describe("IncomeExpenseNetTrendChart — accessibility contract (Req 10.1)", () => {
  it("renders a role=img chart region with a non-empty aria-label", () => {
    renderCard();
    const region = screen.getByRole("img");
    expect(
      (region.getAttribute("aria-label") ?? "").trim().length,
    ).toBeGreaterThan(0);
  });

  it("re-exports its always-present table from the chart module", () => {
    expect(IncomeExpenseNetTrendTable).toBeTypeOf("function");
  });
});

describe("IncomeExpenseNetTrendTable — always-present data table (Req 3.1, 3.3, 3.4)", () => {
  it("renders one row per Data_Year in ascending order with formatted amounts", () => {
    render(<IncomeExpenseNetTrendTable data={DATA} />);
    const table = screen.getByRole("table");
    const bodyRows = within(table).getAllByRole("row").slice(1); // drop header
    expect(bodyRows).toHaveLength(SERIES.years.length);

    const years = within(table)
      .getAllByRole("rowheader")
      .map((cell) => cell.textContent);
    expect(years).toEqual(["2023", "2024"]);

    expect(within(table).getByText("$1,500.00")).toBeInTheDocument();
    expect(within(table).getByText("$250.00")).toBeInTheDocument();
    expect(within(table).getByText("$1,250.00")).toBeInTheDocument();
  });

  it("carries a textual loss cue on a year with negative net (Req 3.4)", () => {
    render(<IncomeExpenseNetTrendTable data={DATA} />);
    expect(screen.getByText(/\(loss\)/i)).toBeInTheDocument();
    expect(screen.getByText("-$800.00")).toBeInTheDocument();
  });
});

describe("IncomeExpenseNetTrendChart — accessibility (axe)", () => {
  it("has no automatically detectable a11y violations", async () => {
    const { container } = renderCard();
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
