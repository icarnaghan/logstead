import { render, screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { ChartCard } from "./ChartCard";
import NetByPropertyTrendChart, {
  NetByPropertyTrendTable,
} from "./NetByPropertyTrendChart";
import { netByPropertyTrend, type PropertyTrendSeries } from "./prepare";
import type { TrendsSeries } from "../../api/dashboard";
import { ThemeProvider } from "../../theme/ThemeProvider";

/**
 * Component tests for the net-by-property **trend** chart + its always-present
 * data table (task 7.4, Requirements 4.1, 4.2, 4.4, 4.5, 10.1, 10.4).
 *
 * Mirrors `NetByPropertyChart.test.tsx`: the chart is rendered NON-lazily
 * inside a `ChartCard` so we assert the accessibility contract (`role="img"` +
 * `aria-label`) and the data-table contract (one row per Data_Year, one column
 * per property series with unique labels, `0.00` for a missing year) without
 * Suspense timing. `ResizeObserver` is stubbed globally in `src/test/setup.ts`,
 * and `useChartColors` subscribes to the theme so the chart is wrapped in a
 * `ThemeProvider`.
 */

// p1 "Maple" has both years; p2 "Maple" collides on name (unique-label suffix)
// and is MISSING 2024 entirely → 0.00 for that year (Req 4.2).
const SERIES: TrendsSeries = {
  years: [
    {
      tax_year: 2023,
      total_income: "0.00",
      total_expenses: "0.00",
      net: "0.00",
      depreciation_total: "0.00",
      properties: [
        {
          property_id: "p1",
          property_name: "Maple",
          total_income: "1500.00",
          total_expenses: "250.00",
          net: "1250.00",
        },
        {
          property_id: "p2",
          property_name: "Maple",
          total_income: "600.00",
          total_expenses: "100.00",
          net: "500.00",
        },
      ],
    },
    {
      tax_year: 2024,
      total_income: "0.00",
      total_expenses: "0.00",
      net: "0.00",
      depreciation_total: "0.00",
      properties: [
        {
          property_id: "p1",
          property_name: "Maple",
          total_income: "2000.00",
          total_expenses: "300.00",
          net: "1700.00",
        },
      ],
    },
  ],
};

const DATA: PropertyTrendSeries[] = netByPropertyTrend(SERIES);

function renderCard(data: PropertyTrendSeries[] = DATA) {
  return render(
    <ThemeProvider>
      <ChartCard
        title="Net by property over time"
        ariaLabel="Net contribution per property for each year with data"
        height={220}
        chart={<NetByPropertyTrendChart data={data} />}
        dataTable={<NetByPropertyTrendTable data={data} />}
      />
    </ThemeProvider>,
  );
}

describe("NetByPropertyTrendChart — accessibility contract (Req 10.1)", () => {
  it("renders a role=img chart region with a non-empty aria-label", () => {
    renderCard();
    const region = screen.getByRole("img");
    expect(
      (region.getAttribute("aria-label") ?? "").trim().length,
    ).toBeGreaterThan(0);
  });

  it("re-exports its always-present table from the chart module", () => {
    expect(NetByPropertyTrendTable).toBeTypeOf("function");
  });
});

describe("NetByPropertyTrendTable — always-present data table (Req 4.1, 4.2, 4.4, 4.5)", () => {
  it("renders one row per Data_Year ascending", () => {
    render(<NetByPropertyTrendTable data={DATA} />);
    const table = screen.getByRole("table");
    const years = within(table)
      .getAllByRole("rowheader")
      .map((cell) => cell.textContent);
    expect(years).toEqual(["2023", "2024"]);
  });

  it("renders one column per property series using unique labels (Req 4.5)", () => {
    render(<NetByPropertyTrendTable data={DATA} />);
    const table = screen.getByRole("table");
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent);
    // The colliding "Maple" names are disambiguated with a running suffix.
    expect(headers).toEqual(["Year", "Maple (1)", "Maple (2)"]);
  });

  it("renders 0.00 for a property missing a given year (Req 4.2)", () => {
    render(<NetByPropertyTrendTable data={DATA} />);
    const table = screen.getByRole("table");
    // p2 (Maple (2)) has no 2024 entry → its 2024 cell is $0.00.
    const rows = within(table).getAllByRole("row").slice(1); // drop header
    const row2024 = rows.find(
      (row) => within(row).queryByText("2024") !== null,
    );
    expect(row2024).toBeDefined();
    expect(within(row2024!).getByText("$0.00")).toBeInTheDocument();
    // p1 (Maple (1)) still carries its real 2024 net.
    expect(within(row2024!).getByText("$1,700.00")).toBeInTheDocument();
  });

  it("shows an empty note when there are no properties", () => {
    render(<NetByPropertyTrendTable data={[]} />);
    expect(
      screen.getByText(/no properties have any activity/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("NetByPropertyTrendChart — accessibility (axe)", () => {
  it("has no automatically detectable a11y violations", async () => {
    const { container } = renderCard();
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
