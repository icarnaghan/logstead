import { render, screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { ChartCard } from "./ChartCard";
import ExpenseByCategoryChart, {
  ExpenseByCategoryTable,
} from "./ExpenseByCategoryChart";
import type { CategoryDatum } from "./prepare";
import { ThemeProvider } from "../../theme/ThemeProvider";

/**
 * Component tests for the expense-by-category chart + its always-present data
 * table (task 17.2, Requirements 16.1–16.3, 12.1, 12.2).
 *
 * The chart is rendered NON-lazily (imported directly) inside a `ChartCard` so
 * we assert the accessibility contract (`role="img"` + `aria-label`) and the
 * data-table contract (one row per category, formatted amounts, descending
 * order) without Suspense timing. `ResizeObserver` is stubbed globally in
 * `src/test/setup.ts`, and `useChartColors` subscribes to the theme so the
 * chart is wrapped in a `ThemeProvider`.
 */

const DATA: CategoryDatum[] = [
  { label: "Repairs", cents: 120000 },
  { label: "Insurance", cents: 45000 },
  { label: "Utilities", cents: 9900 },
];

function renderCard(data: CategoryDatum[] = DATA) {
  return render(
    <ThemeProvider>
      <ChartCard
        title="Expenses by category"
        ariaLabel="Expenses by Schedule E category, ranked highest to lowest"
        chart={<ExpenseByCategoryChart data={data} />}
        dataTable={<ExpenseByCategoryTable data={data} />}
      />
    </ThemeProvider>,
  );
}

describe("ExpenseByCategoryChart — accessibility contract (Req 12.1, 12.2)", () => {
  it("renders a role=img chart region with a non-empty aria-label", () => {
    renderCard();
    const region = screen.getByRole("img");
    expect(region.getAttribute("aria-label")).toBeTruthy();
    expect(
      (region.getAttribute("aria-label") ?? "").trim().length,
    ).toBeGreaterThan(0);
  });
});

describe("ExpenseByCategoryTable — always-present data table (Req 16.1, 16.3)", () => {
  it("renders one row per category with formatted amounts", () => {
    render(<ExpenseByCategoryTable data={DATA} />);
    const table = screen.getByRole("table");
    const bodyRows = within(table).getAllByRole("row").slice(1); // drop header
    expect(bodyRows).toHaveLength(DATA.length);

    expect(within(table).getByText("Repairs")).toBeInTheDocument();
    expect(within(table).getByText("$1,200.00")).toBeInTheDocument();
    expect(within(table).getByText("Insurance")).toBeInTheDocument();
    expect(within(table).getByText("$450.00")).toBeInTheDocument();
    expect(within(table).getByText("Utilities")).toBeInTheDocument();
    expect(within(table).getByText("$99.00")).toBeInTheDocument();
  });

  it("reflects the caller's descending order in row order (Req 16.3)", () => {
    render(<ExpenseByCategoryTable data={DATA} />);
    const table = screen.getByRole("table");
    const rowHeaders = within(table)
      .getAllByRole("rowheader")
      .map((cell) => cell.textContent);
    expect(rowHeaders).toEqual(["Repairs", "Insurance", "Utilities"]);
  });

  it("shows an empty note when there are no expense categories", () => {
    render(<ExpenseByCategoryTable data={[]} />);
    expect(
      screen.getByText(/no expense categories have any activity/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("ExpenseByCategoryChart — accessibility (axe)", () => {
  it("has no automatically detectable a11y violations", async () => {
    const { container } = renderCard();
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
