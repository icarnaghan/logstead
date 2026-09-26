import { render, screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { ChartCard } from "./ChartCard";
import DepreciationChart from "./DepreciationChart";
import { depreciationSeries } from "./prepare";
import { ScheduleTable } from "../assets/ScheduleTable";
import type { ScheduleRow } from "../../api/assets";
import { ThemeProvider } from "../../theme/ThemeProvider";

/**
 * Component tests for the depreciation-schedule chart + its always-present data
 * table (task 19.2, Requirements 19.1, 19.3, 12.1, 12.2).
 *
 * The chart is rendered NON-lazily (imported directly) inside a `ChartCard`
 * whose `dataTable` reuses the existing `ScheduleTable`, so we assert the
 * accessibility contract (`role="img"` + `aria-label`), the always-present data
 * table alongside the chart, and the text series labels — without Suspense
 * timing. `ResizeObserver` is stubbed globally in `src/test/setup.ts`, and
 * `useChartColors` subscribes to the theme so the chart is wrapped in a
 * `ThemeProvider`.
 */

const ROWS: ScheduleRow[] = [
  {
    tax_year: 2023,
    amount: "5833.33",
    remaining_basis: "269166.67",
    method: "straight-line",
    convention: "mid-month",
  },
  {
    tax_year: 2024,
    amount: "10000.00",
    remaining_basis: "259166.67",
    method: "straight-line",
    convention: "mid-month",
  },
];

const CAPTION = "Year-by-year depreciation schedule for Rental building";

function renderCard(rows: ScheduleRow[] = ROWS) {
  return render(
    <ThemeProvider>
      <ChartCard
        title="Depreciation & remaining basis"
        ariaLabel="Year-by-year depreciation and remaining basis for Rental building"
        chart={<DepreciationChart data={depreciationSeries(rows)} />}
        dataTable={<ScheduleTable caption={CAPTION} rows={rows} />}
      />
    </ThemeProvider>,
  );
}

describe("DepreciationChart — accessibility contract (Req 12.1, 12.2)", () => {
  it("renders a role=img chart region with a non-empty aria-label", () => {
    renderCard();
    const region = screen.getByRole("img");
    expect(
      (region.getAttribute("aria-label") ?? "").trim().length,
    ).toBeGreaterThan(0);
  });

  it("renders the schedule data table alongside the chart (Req 19.3)", () => {
    renderCard();
    const table = screen.getByRole("table");
    expect(within(table).getByText("2023")).toBeInTheDocument();
    expect(within(table).getByText("$5,833.33")).toBeInTheDocument();
    expect(within(table).getByText("$269,166.67")).toBeInTheDocument();
    expect(within(table).getByText("2024")).toBeInTheDocument();
  });

  it("labels both series with text, not color alone (Req 12.4)", () => {
    renderCard();
    // The legend renders each series name as text.
    expect(screen.getByText("Remaining basis")).toBeInTheDocument();
    expect(screen.getByText("Depreciation amount")).toBeInTheDocument();
  });
});

describe("DepreciationChart — accessibility (axe)", () => {
  it("has no automatically detectable a11y violations", async () => {
    const { container } = renderCard();
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
