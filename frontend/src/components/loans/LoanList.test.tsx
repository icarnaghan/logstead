import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { LoanList } from "./LoanList";
import type { Loan } from "../../api/loans";

/**
 * Component tests for the loan list (Requirements 11.1, 9.7).
 */

function loan(overrides: Partial<Loan> = {}): Loan {
  return {
    id: "loan-1",
    property_id: "prop-1",
    description: "Primary mortgage",
    annual_interest_rate: "6.875",
    monthly_payment: "1970.79",
    anchor_balance: "214500.00",
    anchor_date: "2025-06-01",
    extra_principal: "0.00",
    original_principal: null,
    closing_date: null,
    payoff_date: null,
    include_in_report: true,
    interest_overrides: {},
    remaining_payments: 148,
    next_payment_date: "2025-07-01",
    projected_payoff_date: "2037-10-01",
    payoff_balance: null,
    status: "active",
    created_at: "2023-01-01T00:00:00Z",
    updated_at: "2023-01-01T00:00:00Z",
    ...overrides,
  };
}

/** The loan list table. */
function table() {
  return within(screen.getByRole("table"));
}

function handlers() {
  return {
    onSelect: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    onCreate: vi.fn(),
  };
}

describe("LoanList — rendering (Req 9.6)", () => {
  it("renders description, anchor balance and date, rate, payment, remaining payments and status", () => {
    render(<LoanList loans={[loan()]} {...handlers()} />);

    const table = screen.getByRole("table");
    expect(within(table).getByText("Primary mortgage")).toBeInTheDocument();
    expect(within(table).getByText("$214,500.00")).toBeInTheDocument();
    expect(within(table).getByText("as of 2025-06-01")).toBeInTheDocument();
    expect(within(table).getByText("6.875%")).toBeInTheDocument();
    expect(within(table).getByText("$1,970.79")).toBeInTheDocument();
    expect(within(table).getByText("148 payments")).toBeInTheDocument();
    expect(within(table).getByText("Payoff 2037-10-01")).toBeInTheDocument();
    expect(within(table).getByText("Active")).toBeInTheDocument();
  });

  it("renders ended status and singular payment count", () => {
    render(
      <LoanList
        loans={[loan({ status: "ended", remaining_payments: 1 })]}
        {...handlers()}
      />,
    );
    expect(table().getByText("Ended")).toBeInTheDocument();
    expect(table().getByText("1 payment")).toBeInTheDocument();
  });

  it("shows the payoff balance when a payoff date truncates the schedule", () => {
    render(
      <LoanList
        loans={[
          loan({
            projected_payoff_date: null,
            payoff_date: "2027-01-01",
            payoff_balance: "100000.00",
          }),
        ]}
        {...handlers()}
      />,
    );
    expect(
      table().getByText("Payoff balance $100,000.00"),
    ).toBeInTheDocument();
  });

  it("renders one row per loan", () => {
    render(
      <LoanList
        loans={[
          loan({ id: "a", description: "First" }),
          loan({ id: "b", description: "Second" }),
        ]}
        {...handlers()}
      />,
    );
    expect(table().getByText("First")).toBeInTheDocument();
    expect(table().getByText("Second")).toBeInTheDocument();
  });
});

describe("LoanList — actions", () => {
  it("calls handlers with the loan and names buttons by description", async () => {
    const user = userEvent.setup();
    const h = handlers();
    const l = loan();
    render(<LoanList loans={[l]} {...h} />);

    await user.click(
      table().getByRole("button", { name: "Select Primary mortgage" }),
    );
    await user.click(
      table().getByRole("button", { name: "Edit Primary mortgage" }),
    );
    await user.click(
      table().getByRole("button", { name: "Delete Primary mortgage" }),
    );

    expect(h.onSelect).toHaveBeenCalledWith(l);
    expect(h.onEdit).toHaveBeenCalledWith(l);
    expect(h.onDelete).toHaveBeenCalledWith(l);
  });

  it("marks the selected loan with aria-pressed", () => {
    render(
      <LoanList
        loans={[
          loan({ id: "a", description: "A" }),
          loan({ id: "b", description: "B" }),
        ]}
        selectedLoanId="a"
        {...handlers()}
      />,
    );
    expect(table().getByRole("button", { name: "Select A" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(table().getByRole("button", { name: "Select B" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});

describe("LoanList — empty state (Req 9.7)", () => {
  it("shows the empty state with a create control", async () => {
    const user = userEvent.setup();
    const h = handlers();
    render(<LoanList loans={[]} {...h} />);

    expect(screen.getByText(/no loans yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /add loan/i }));
    expect(h.onCreate).toHaveBeenCalledTimes(1);
  });
});

describe("LoanList — accessibility", () => {
  it("has no axe violations with loans", async () => {
    const { container } = render(<LoanList loans={[loan()]} {...handlers()} />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it("has no axe violations when empty", async () => {
    const { container } = render(<LoanList loans={[]} {...handlers()} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
