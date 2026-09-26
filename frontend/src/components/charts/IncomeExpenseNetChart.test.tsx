import { render, screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { ChartCard } from "./ChartCard";
import IncomeExpenseNetChart, {
  IncomeExpenseNetTable,
} from "./IncomeExpenseNetChart";
import { incomeExpenseNet, type IncomeExpenseNetDatum } from "./prepare";
import { ThemeProvider } from "../../theme/ThemeProvider";

/**
 * Component tests for the compact income / expenses / net chart + its
 * always-present data table (task 17.5, Requirements 17.1–17.3, 12.1, 12.2,
 * 12.4).
 *
 * The chart is rendered NON-lazily (imported directly) inside a `ChartCard` so
 * we assert the accessibility contract (`role="img"` + `aria-label`) and the
 * data-table contract (three rows, formatted amounts, textual net cue) without
 * Suspense timing. `ResizeObserver` is stubbed globally in `src/test/setup.ts`,
 * and `useChartColors` subscribes to the theme so the chart is wrapped in a
 * `ThemeProvider`.
 */

const INCOME_DATA: IncomeExpenseNetDatum[] = incomeExpenseNet({
  total_income: "1500.00",
  total_expenses: "250.00",
  net: "1250.00",
});

const LOSS_DATA: IncomeExpenseNetDatum[] = incomeExpenseNet({
  total_income: "100.00",
  total_expenses: "900.00",
  net: "-800.00",
});

function renderCard(data: IncomeExpenseNetDatum[] = INCOME_DATA) {
  return render(
    <ThemeProvider>
      <ChartCard
        title="Income, expenses & net"
        ariaLabel="Portfolio income, expenses, and net for the selected year"
        height={220}
        chart={<IncomeExpenseNetChart data={data} />}
        dataTable={<IncomeExpenseNetTable data={data} />}
      />
    </ThemeProvider>,
  );
}

describe("IncomeExpenseNetChart — accessibility contract (Req 12.1, 12.2)", () => {
  it("renders a role=img chart region with a non-empty aria-label", () => {
    renderCard();
    const region = screen.getByRole("img");
    expect((region.getAttribute("aria-label") ?? "").trim().length).toBeGreaterThan(
      0,
    );
  });
});

describe("IncomeExpenseNetTable — always-present data table (Req 17, 12.4)", () => {
  it("renders Income / Expenses / Net rows with formatted amounts", () => {
    render(<IncomeExpenseNetTable data={INCOME_DATA} />);
    const table = screen.getByRole("table");
    const bodyRows = within(table).getAllByRole("row").slice(1); // drop header
    expect(bodyRows).toHaveLength(3);

    expect(within(table).getByText("Income")).toBeInTheDocument();
    expect(within(table).getByText("$1,500.00")).toBeInTheDocument();
    expect(within(table).getByText("Expenses")).toBeInTheDocument();
    expect(within(table).getByText("$250.00")).toBeInTheDocument();
    expect(within(table).getByText("Net")).toBeInTheDocument();
    expect(within(table).getByText("$1,250.00")).toBeInTheDocument();
  });

  it("carries a textual gain cue on the Net row when positive (Req 12.4)", () => {
    render(<IncomeExpenseNetTable data={INCOME_DATA} />);
    expect(screen.getByText(/\(income\)/i)).toBeInTheDocument();
  });

  it("carries a textual loss cue on the Net row when negative (Req 12.4)", () => {
    render(<IncomeExpenseNetTable data={LOSS_DATA} />);
    expect(screen.getByText(/\(loss\)/i)).toBeInTheDocument();
    expect(screen.getByText("-$800.00")).toBeInTheDocument();
  });
});

describe("IncomeExpenseNetChart — theme toggle keeps the chart present (Req 11.3)", () => {
  it("keeps the chart region present after a theme re-render", () => {
    const { container, rerender } = renderCard();
    expect(within(container).getByRole("img")).toBeInTheDocument();

    // Re-render under a fresh ThemeProvider (colors are CSS-variable strings,
    // so a re-render under a different theme keeps the chart present; deep color
    // assertions are brittle in jsdom, Req 11.3).
    rerender(
      <ThemeProvider>
        <ChartCard
          title="Income, expenses & net"
          ariaLabel="Portfolio income, expenses, and net for the selected year"
          height={220}
          chart={<IncomeExpenseNetChart data={INCOME_DATA} />}
          dataTable={<IncomeExpenseNetTable data={INCOME_DATA} />}
        />
      </ThemeProvider>,
    );
    expect(within(container).getByRole("img")).toBeInTheDocument();
  });
});

describe("IncomeExpenseNetChart — accessibility (axe)", () => {
  it("has no automatically detectable a11y violations", async () => {
    const { container } = renderCard();
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
