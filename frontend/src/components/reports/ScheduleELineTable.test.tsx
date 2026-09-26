import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScheduleELineTable } from "./ScheduleELineTable";
import type { ReportLine } from "../../api/reports";

/**
 * Component tests for {@link ScheduleELineTable} (task 24.3, Requirement 10.1).
 *
 * Verifies each line row renders its line number, label, kind, and formatted
 * money amount under an accessible caption, that the empty-lines message is
 * shown when there is no activity, and that the table is numbers-only (no
 * chart/canvas/svg).
 */

const LINES: ReportLine[] = [
  { line: 3, label: "Rents received", kind: "income", total: "24000.00" },
  { line: 14, label: "Repairs", kind: "expense", total: "1200.50" },
];

describe("ScheduleELineTable — rows (Req 10.1)", () => {
  it("renders a row per line with line #, label, kind and formatted amount", () => {
    render(
      <ScheduleELineTable caption="Schedule E lines for 2024" lines={LINES} />,
    );

    const table = screen.getByRole("table");
    const rowgroups = within(table).getAllByRole("rowgroup");
    // Second rowgroup is the tbody; one row per line.
    const bodyRows = within(rowgroups[1]).getAllByRole("row");
    expect(bodyRows).toHaveLength(2);

    const rents = within(rowgroups[1]).getByRole("row", {
      name: /rents received/i,
    });
    expect(within(rents).getByText("3")).toBeInTheDocument();
    expect(within(rents).getByText("Rents received")).toBeInTheDocument();
    expect(within(rents).getByText("income")).toBeInTheDocument();
    expect(within(rents).getByText("$24,000.00")).toBeInTheDocument();

    const repairs = within(rowgroups[1]).getByRole("row", { name: /repairs/i });
    expect(within(repairs).getByText("14")).toBeInTheDocument();
    expect(within(repairs).getByText("expense")).toBeInTheDocument();
    expect(within(repairs).getByText("$1,200.50")).toBeInTheDocument();
  });

  it("exposes an accessible caption", () => {
    render(
      <ScheduleELineTable
        caption="Schedule E income lines for Maple Duplex, tax year 2024"
        lines={LINES}
      />,
    );

    expect(
      screen.getByRole("table", {
        name: /schedule e income lines for maple duplex, tax year 2024/i,
      }),
    ).toBeInTheDocument();
  });
});

describe("ScheduleELineTable — empty state", () => {
  it("shows the no-activity message and no table when there are no lines", () => {
    render(<ScheduleELineTable caption="Empty" lines={[]} />);

    expect(
      screen.getByText(/no schedule e lines have any activity/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("ScheduleELineTable — numbers-only", () => {
  it("renders no chart, canvas, or svg element", () => {
    const { container } = render(
      <ScheduleELineTable caption="Schedule E lines" lines={LINES} />,
    );

    expect(container.querySelector("canvas")).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
  });
});
