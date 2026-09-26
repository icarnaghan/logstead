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

    const header = sectionByHeading(/maple duplex/i);
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

    const header = sectionByHeading(/maple duplex/i);
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
    expect(within(income).getByText("$24,000.00")).toBeInTheDocument();
    // An expense line must NOT appear in the income section.
    expect(within(income).queryByText("Repairs")).not.toBeInTheDocument();
  });

  it("places expense lines in the Expenses section with formatted amounts", () => {
    render(<ReportView report={makeReport()} />);

    const expenses = sectionByHeading(/^expenses$/i);
    expect(within(expenses).getByText("Repairs")).toBeInTheDocument();
    expect(within(expenses).getByText("$1,200.00")).toBeInTheDocument();
    expect(within(expenses).queryByText("Rents received")).not.toBeInTheDocument();
  });
});

describe("ReportView — Line 18 depreciation (Req 10.3)", () => {
  it("renders the Line 18 depreciation total", () => {
    render(<ReportView report={makeReport()} />);

    const dep = sectionByHeading(/depreciation \(line 18\)/i);
    expect(within(dep).getByText("$5,833.33")).toBeInTheDocument();
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
    expect(within(dep).getByText("$0.00")).toBeInTheDocument();
  });
});

describe("ReportView — Line 19 itemization (Req 10.5)", () => {
  it("lists each Other item's description and amount", () => {
    render(<ReportView report={makeReport()} />);

    const other = sectionByHeading(/other expenses \(line 19\)/i);
    expect(within(other).getByText("HOA dues")).toBeInTheDocument();
    expect(within(other).getByText("$100.00")).toBeInTheDocument();
    expect(within(other).getByText("Bank fees")).toBeInTheDocument();
    expect(within(other).getByText("$42.00")).toBeInTheDocument();
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
    const incomeDt = within(totals).getByText("Total income");
    expect(incomeDt.nextElementSibling).toHaveTextContent("$24,000.00");
    const expensesDt = within(totals).getByText("Total expenses");
    expect(expensesDt.nextElementSibling).toHaveTextContent("$7,175.33");

    expect(within(totals).getByText("Net income")).toBeInTheDocument();
    expect(within(totals).queryByText("Net loss")).not.toBeInTheDocument();
    expect(within(totals).getByText("$16,824.67")).toBeInTheDocument();
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
    expect(within(totals).getByText("-$500.00")).toBeInTheDocument();
  });
});

describe("ReportView — numbers-first presentation (Req 11.4/11.5)", () => {
  it("renders no chart, canvas, or svg element", () => {
    const { container } = render(<ReportView report={makeReport()} />);

    expect(container.querySelector("canvas")).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

describe("ReportView — accessibility", () => {
  it("has no automatically detectable a11y violations", async () => {
    const { container } = render(<ReportView report={makeReport()} />);

    expect(await axe(container)).toHaveNoViolations();
  });
});
