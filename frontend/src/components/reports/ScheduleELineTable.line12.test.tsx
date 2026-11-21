import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScheduleELineTable } from "./ScheduleELineTable";
import type { Line12Detail, ReportLine } from "../../api/reports";

/**
 * Unit tests for the Line 12 source label and superseded amount in
 * {@link ScheduleELineTable} (task 13.3, Requirements 10.1-10.5).
 */

const LINES: ReportLine[] = [
  { line: 3, label: "Rents received", kind: "income", total: "24000.00" },
  {
    line: 12,
    label: "Mortgage interest paid to banks",
    kind: "expense",
    total: "9876.54",
  },
];

function line12Row() {
  return screen.getByRole("row", { name: /mortgage interest/i });
}

function rentsRow() {
  return screen.getByRole("row", { name: /rents received/i });
}

describe("ScheduleELineTable — Line 12 source (Req 10.1-10.5)", () => {
  it("labels loan-generated interest and shows the superseded amount", () => {
    const line12: Line12Detail = {
      source: "loan-generated",
      superseded_manual_interest: { amount: "1234.5", count: 3 },
    };
    render(<ScheduleELineTable caption="c" lines={LINES} line12={line12} />);

    const row = line12Row();
    expect(within(row).getByText("Loan-generated")).toBeInTheDocument();
    expect(
      within(row).getByText(
        "Superseded manual interest: $1,234.50 (3 transactions)",
      ),
    ).toBeInTheDocument();
    expect(within(row).getByText("$9,877")).toBeInTheDocument();
    // Only the Line 12 row is affected.
    expect(within(rentsRow()).queryByText("Loan-generated")).toBeNull();
  });

  it("omits the superseded text when nothing was superseded", () => {
    render(
      <ScheduleELineTable
        caption="c"
        lines={LINES}
        line12={{
          source: "loan-generated",
          superseded_manual_interest: { amount: "0.00", count: 0 },
        }}
      />,
    );
    const row = line12Row();
    expect(within(row).getByText("Loan-generated")).toBeInTheDocument();
    expect(within(row).queryByText(/superseded/i)).toBeNull();
  });

  it("renders transaction-entered exactly like a report without loan data", () => {
    const { container: withSource } = render(
      <ScheduleELineTable
        caption="c"
        lines={LINES}
        line12={{
          source: "transaction-entered",
          superseded_manual_interest: { amount: "0.00", count: 0 },
        }}
      />,
    );
    const html = withSource.innerHTML;
    expect(within(withSource).queryByText("Loan-generated")).toBeNull();
    expect(within(withSource).queryByText(/source unavailable/i)).toBeNull();
    expect(within(withSource).queryByText(/superseded/i)).toBeNull();
    expect(html).not.toContain("Loan-generated");
  });

  it.each([
    ["missing", undefined],
    ["null", null],
    [
      "unrecognized",
      {
        source: "bogus",
        superseded_manual_interest: { amount: "5.00", count: 1 },
      } as unknown as Line12Detail,
    ],
  ])("shows 'source unavailable' when line12 is %s", (_name, line12) => {
    render(<ScheduleELineTable caption="c" lines={LINES} line12={line12} />);
    const row = line12Row();
    expect(
      within(row).getByText("Line 12 source unavailable"),
    ).toBeInTheDocument();
    expect(within(row).queryByText("Loan-generated")).toBeNull();
    expect(within(row).queryByText(/superseded/i)).toBeNull();
    expect(within(row).getByText("$9,877")).toBeInTheDocument();
    expect(within(rentsRow()).queryByText(/source unavailable/i)).toBeNull();
  });
});
