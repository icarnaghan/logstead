import { render, screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { ScheduleTable } from "./ScheduleTable";
import type { ScheduleRow } from "../../api/assets";

/**
 * Component tests for the depreciation schedule display (task 23.2,
 * Requirement 9.4).
 *
 * The schedule is deliberately a numeric data table — never a chart. These
 * tests assert the tax_year / amount / remaining_basis columns render in
 * order, money strings render verbatim (no float drift), the empty state
 * message appears, the table exposes an accessible caption, and there is no
 * canvas/svg chart element.
 */

function row(overrides: Partial<ScheduleRow> = {}): ScheduleRow {
  return {
    tax_year: 2023,
    amount: "5833.33",
    remaining_basis: "269166.67",
    method: "straight-line",
    convention: "mid-month",
    ...overrides,
  };
}

const rows: ScheduleRow[] = [
  row({ tax_year: 2023, amount: "5833.33", remaining_basis: "269166.67" }),
  row({ tax_year: 2024, amount: "10000.00", remaining_basis: "259166.67" }),
  row({ tax_year: 2025, amount: "10000.00", remaining_basis: "249166.67" }),
];

describe("ScheduleTable — numeric table (Req 9.4)", () => {
  it("renders a table with tax_year / amount / remaining_basis rows in order", () => {
    render(<ScheduleTable caption="Depreciation for Rental building" rows={rows} />);

    const table = screen.getByRole("table");
    const bodyRows = within(table).getAllByRole("row");
    // Header row + one row per schedule entry.
    expect(bodyRows).toHaveLength(rows.length + 1);

    const dataRows = bodyRows.slice(1);
    expect(within(dataRows[0]).getByText("2023")).toBeInTheDocument();
    expect(within(dataRows[1]).getByText("2024")).toBeInTheDocument();
    expect(within(dataRows[2]).getByText("2025")).toBeInTheDocument();
  });

  it("renders money strings verbatim (no float coercion)", () => {
    render(<ScheduleTable caption="Depreciation schedule" rows={rows} />);

    const table = screen.getByRole("table");
    expect(within(table).getByText("5833.33")).toBeInTheDocument();
    expect(within(table).getByText("269166.67")).toBeInTheDocument();
    expect(within(table).getByText("249166.67")).toBeInTheDocument();
    // Trailing-zero amounts are preserved exactly.
    expect(within(table).getAllByText("10000.00").length).toBeGreaterThan(0);
  });

  it("exposes an accessible caption", () => {
    render(
      <ScheduleTable caption="Depreciation for Rental building" rows={rows} />,
    );

    const table = screen.getByRole("table", {
      name: /depreciation for rental building/i,
    });
    expect(table).toBeInTheDocument();
  });

  it("shows a no-schedule message when the schedule is empty", () => {
    render(<ScheduleTable caption="Empty schedule" rows={[]} />);

    expect(screen.getByText(/no depreciation schedule/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders no chart element (no canvas/svg)", () => {
    const { container } = render(
      <ScheduleTable caption="Depreciation schedule" rows={rows} />,
    );

    expect(container.querySelector("canvas")).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
  });

  it("has no detectable accessibility violations", async () => {
    const { container } = render(
      <ScheduleTable caption="Depreciation for Rental building" rows={rows} />,
    );

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
