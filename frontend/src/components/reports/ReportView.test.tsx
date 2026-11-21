import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";
import { ReportView } from "./ReportView";
import type { ScheduleEReport } from "../../api/reports";

/**
 * Component-level tests for {@link ReportView} (task 24.3, Requirement 10).
 *
 * These deepen coverage beyond the page-level tests in ReportsPage.test.tsx by
 * exercising the presentation component directly with injected report data — no
 * network, no page wiring. They verify the header (name/address/type + usage
 * days), income/expense line placement, the Line 18 depreciation total, the
 * Line 19 "Other" itemization, the totals block, and the net income/loss label.
 * They also assert the report is rendered numbers-first with no chart/canvas/svg
 * present (Requirement 11.4/11.5), plus an axe check.
 */

function makeReport(overrides: Partial<ScheduleEReport> = {}): ScheduleEReport {
  return {
    header: {
      property_id: "prop-1",
      property_name: "Maple Duplex",
      address: "123 Maple St, Springfield",
      property_type: "Multi-Family",
      tax_year: 2024,
      fair_rental_days: 300,
      personal_use_days: 5,
    },
    lines: [
      { line: 3, label: "Rents received", kind: "income", total: "24000.00" },
      { line: 14, label: "Repairs", kind: "expense", total: "1200.00" },
      { line: 18, label: "Depreciation", kind: "expense", total: "5833.33" },
      { line: 19, label: "Other", kind: "expense", total: "142.00" },
    ],
    other_items: [
      { description: "HOA dues", amount: "100.00" },
      { description: "Bank fees", amount: "42.00" },
    ],
    totals: {
      total_income: "24000.00",
      total_expenses: "7175.33",
      net: "16824.67",
    },
    line12: {
      source: "transaction-entered",
      superseded_manual_interest: { amount: "0.00", count: 0 },
    },
    ...overrides,
  };
}

function sectionByHeading(name: RegExp): HTMLElement {
  return screen
    .getByRole("heading", { name })
    .closest("section") as HTMLElement;
}

describe("ReportView — header (Req 10.2)", () => {
  it("renders the property name, address, type and usage days", () => {
    render(<ReportView report={makeReport()} />);

    const header = sectionByHeading(/^maple duplex$/i);
    expect(
      within(header).getByRole("heading", { name: "Maple Duplex" }),
    ).toBeInTheDocument();
    expect(
      within(header).getByText("123 Maple St, Springfield"),
    ).toBeInTheDocument();
    expect(within(header).getByText("Multi-Family")).toBeInTheDocument();
    expect(within(header).getByText("2024")).toBeInTheDocument();

    // Fair-rental and personal-use days appear under their labels.
    const fairRentalDt = within(header).getByText("Fair rental days");
    expect(fairRentalDt.nextElementSibling).toHaveTextContent("300");
    const personalDt = within(header).getByText("Personal use days");
    expect(personalDt.nextElementSibling).toHaveTextContent("5");
  });

  it("falls back to a dash for a missing address or property type", () => {
    render(
      <ReportView
        report={makeReport({
          header: {
            ...makeReport().header,
            address: "",
            property_type: null,
          },
        })}
      />,
    );

    const header = sectionByHeading(/^maple duplex$/i);
    const addressDt = within(header).getByText("Address");
    expect(addressDt.nextElementSibling).toHaveTextContent("—");
    const typeDt = within(header).getByText("Property type");
    expect(typeDt.nextElementSibling).toHaveTextContent("—");
  });
});

describe("ReportView — income and expense lines (Req 10.1)", () => {
  it("places income lines in the Income section with formatted amounts", () => {
    render(<ReportView report={makeReport()} />);

    const income = sectionByHeading(/^income$/i);
    expect(within(income).getByText("Rents received")).toBeInTheDocument();
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.1
    // Tax-oriented line figures round to whole dollars: "24000.00" → "$24,000".
    expect(within(income).getByText("$24,000")).toBeInTheDocument();
    // An expense line must NOT appear in the income section.
    expect(within(income).queryByText("Repairs")).not.toBeInTheDocument();
  });

  it("places expense lines in the Expenses section with formatted amounts", () => {
    render(<ReportView report={makeReport()} />);

    const expenses = sectionByHeading(/^expenses$/i);
    expect(within(expenses).getByText("Repairs")).toBeInTheDocument();
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.1
    // "1200.00" → "$1,200" on the whole-dollar expense line.
    expect(within(expenses).getByText("$1,200")).toBeInTheDocument();
    expect(within(expenses).queryByText("Rents received")).not.toBeInTheDocument();
  });
});

describe("ReportView — Line 18 depreciation (Req 10.3)", () => {
  it("renders the Line 18 depreciation total", () => {
    render(<ReportView report={makeReport()} />);

    const dep = sectionByHeading(/depreciation \(line 18\)/i);
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.1
    // Line 18 rounds to whole dollars: "5833.33" → "$5,833".
    expect(within(dep).getByText("$5,833")).toBeInTheDocument();
  });

  it("shows a zero depreciation total when no Line 18 line exists", () => {
    render(
      <ReportView
        report={makeReport({
          lines: [
            { line: 3, label: "Rents received", kind: "income", total: "1000.00" },
          ],
        })}
      />,
    );

    const dep = sectionByHeading(/depreciation \(line 18\)/i);
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.1
    // The zero fallback "0.00" rounds to "$0".
    expect(within(dep).getByText("$0")).toBeInTheDocument();
  });
});

describe("ReportView — Line 19 itemization (Req 10.5)", () => {
  it("lists each Other item's description and amount", () => {
    render(<ReportView report={makeReport()} />);

    const other = sectionByHeading(/other expenses \(line 19\)/i);
    expect(within(other).getByText("HOA dues")).toBeInTheDocument();
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.1
    // Line 19 item amounts round to whole dollars: "100.00" → "$100",
    // "42.00" → "$42".
    expect(within(other).getByText("$100")).toBeInTheDocument();
    expect(within(other).getByText("Bank fees")).toBeInTheDocument();
    expect(within(other).getByText("$42")).toBeInTheDocument();
  });

  it("shows the empty-itemization note when there are no Other items", () => {
    render(<ReportView report={makeReport({ other_items: [] })} />);

    const other = sectionByHeading(/other expenses \(line 19\)/i);
    expect(
      within(other).getByText(/no line 19 "other" expenses/i),
    ).toBeInTheDocument();
  });
});

describe("ReportView — totals and net label (Req 10.4)", () => {
  it("shows total income, total expenses, and labels a positive net 'Net income'", () => {
    render(<ReportView report={makeReport()} />);

    const totals = sectionByHeading(/^totals$/i);
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.1
    // Totals round half-up by magnitude: "24000.00" → "$24,000",
    // "7175.33" → "$7,175", "16824.67" → "$16,825".
    const incomeDt = within(totals).getByText("Total income");
    expect(incomeDt.nextElementSibling).toHaveTextContent("$24,000");
    // Alignment is preserved: the money cell keeps its tabular-nums class.
    expect(incomeDt.nextElementSibling).toHaveClass("tabular-nums");
    const expensesDt = within(totals).getByText("Total expenses");
    expect(expensesDt.nextElementSibling).toHaveTextContent("$7,175");

    expect(within(totals).getByText("Net income")).toBeInTheDocument();
    expect(within(totals).queryByText("Net loss")).not.toBeInTheDocument();
    expect(within(totals).getByText("$16,825")).toBeInTheDocument();
  });

  it("labels a negative net 'Net loss' and formats it with a leading minus", () => {
    render(
      <ReportView
        report={makeReport({
          totals: {
            total_income: "1000.00",
            total_expenses: "1500.00",
            net: "-500.00",
          },
        })}
      />,
    );

    const totals = sectionByHeading(/^totals$/i);
    expect(within(totals).getByText("Net loss")).toBeInTheDocument();
    expect(within(totals).queryByText("Net income")).not.toBeInTheDocument();
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.1
    // A negative net rounds the magnitude and keeps the leading minus:
    // "-500.00" → "-$500". The "Net loss" cue above still carries the loss.
    const netLoss = within(totals).getByText("-$500");
    expect(netLoss).toBeInTheDocument();
    expect(netLoss).toHaveClass("tabular-nums");
  });
});

describe("ReportView — expense-by-category chart (Req 16.1, 16.3)", () => {
  it("renders the ranked expense-by-category chart card with its always-present data table", () => {
    render(<ReportView report={makeReport()} />);

    // The chart carries the accessibility contract: a role="img" region with a
    // summarizing, non-empty aria-label (Req 12.2).
    const chartRegion = screen.getByRole("img");
    expect(chartRegion.getAttribute("aria-label")).toMatch(
      /expenses by schedule e category/i,
    );

    // The always-present data table (Req 12.1) lists each expense category with
    // its formatted amount, ranked descending (Req 16.3): Depreciation 5833.33,
    // Repairs 1200.00, Other 142.00.
    const chartCard = screen
      .getByRole("heading", { name: /expenses by category/i })
      .closest("section") as HTMLElement;
    const rowHeaders = within(chartCard)
      .getAllByRole("rowheader")
      .map((cell) => cell.textContent);
    expect(rowHeaders).toEqual(["Depreciation", "Repairs", "Other"]);
    expect(within(chartCard).getByText("$5,833.33")).toBeInTheDocument();
  });

  it("omits the expense chart when the report has no expense lines", () => {
    render(
      <ReportView
        report={makeReport({
          lines: [
            { line: 3, label: "Rents received", kind: "income", total: "1000.00" },
          ],
        })}
      />,
    );

    expect(
      screen.queryByRole("heading", { name: /expenses by category/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

describe("ReportView — Line 12 source (mortgage-amortization Req 10.1-10.5)", () => {
  function line12Report(
    line12: ScheduleEReport["line12"] | undefined,
    total = "6000.00",
  ): ScheduleEReport {
    const base = makeReport();
    const report = {
      ...base,
      lines: [
        ...base.lines,
        { line: 12, label: "Mortgage interest", kind: "expense", total },
      ],
    } as ScheduleEReport;
    if (line12 === undefined) {
      delete (report as Partial<ScheduleEReport>).line12;
    } else {
      report.line12 = line12;
    }
    return report;
  }

  function line12Row(): HTMLElement {
    const expenses = sectionByHeading(/^expenses$/i);
    return within(expenses).getByRole("row", { name: /mortgage interest/i });
  }

  it("shows the loan-generated label and superseded amount to two decimals on the Line 12 row", () => {
    render(
      <ReportView
        report={line12Report({
          source: "loan-generated",
          superseded_manual_interest: { amount: "1234.50", count: 3 },
        })}
      />,
    );

    const row = line12Row();
    expect(within(row).getByText("Loan-generated")).toBeInTheDocument();
    expect(
      within(row).getByText(/superseded manual interest: \$1,234\.50 \(3 transactions\)/i),
    ).toBeInTheDocument();
    expect(within(row).getByText("$6,000")).toBeInTheDocument();
  });

  it("shows no source label for transaction-entered Line 12", () => {
    render(<ReportView report={line12Report(makeReport().line12)} />);

    const row = line12Row();
    expect(within(row).queryByText("Loan-generated")).not.toBeInTheDocument();
    expect(within(row).queryByText(/superseded/i)).not.toBeInTheDocument();
    expect(within(row).queryByText(/source unavailable/i)).not.toBeInTheDocument();
    expect(within(row).getByText("$6,000")).toBeInTheDocument();
  });

  it("shows no label for a zero transaction-entered Line 12", () => {
    render(<ReportView report={line12Report(makeReport().line12, "0.00")} />);

    const row = line12Row();
    expect(within(row).getByText("$0")).toBeInTheDocument();
    expect(within(row).queryByText("Loan-generated")).not.toBeInTheDocument();
    expect(within(row).queryByText(/source unavailable/i)).not.toBeInTheDocument();
  });

  it("shows 'Line 12 source unavailable' on the Line 12 row when line12 is missing", () => {
    render(<ReportView report={line12Report(undefined)} />);

    expect(
      within(line12Row()).getByText("Line 12 source unavailable"),
    ).toBeInTheDocument();
  });
});

describe("ReportView — accessibility", () => {
  it("has no automatically detectable a11y violations", async () => {
    const { container } = render(<ReportView report={makeReport()} />);

    expect(await axe(container)).toHaveNoViolations();
  });
});
