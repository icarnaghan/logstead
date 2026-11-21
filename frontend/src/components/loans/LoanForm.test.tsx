import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { LoanForm } from "./LoanForm";
import { todayIso } from "./loanFormModel";

/**
 * Component tests for the balance-anchor loan form
 * (Requirements 10.1-10.8, 11.9).
 */

const PREVIEW = "loan-preview";
const ANCHOR_DATE = "Anchor date";

async function fillValid(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Annual interest rate (%)"), "0");
  await user.type(
    screen.getByLabelText("Monthly payment (principal and interest)"),
    "100",
  );
  await user.type(screen.getByLabelText("Anchor balance"), "1200");
  fireEvent.change(screen.getByLabelText(ANCHOR_DATE), {
    target: { value: "2025-01-31" },
  });
}

describe("LoanForm", () => {
  it("renders all fields with their labels", () => {
    render(<LoanForm onSubmit={vi.fn()} />);
    for (const label of [
      "Description",
      "Annual interest rate (%)",
      "Monthly payment (principal and interest)",
      "Anchor balance",
      ANCHOR_DATE,
      "Extra principal per month (optional)",
      "Payoff date (optional)",
      "Original principal (optional)",
      "Closing date (optional)",
      "Include in report",
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Add loan" })).toBeInTheDocument();
  });

  it("defaults the anchor date to today", () => {
    render(<LoanForm onSubmit={vi.fn()} />);
    expect(screen.getByLabelText(ANCHOR_DATE)).toHaveValue(todayIso());
  });

  it("links the anchor help text to the anchor balance and date", () => {
    render(<LoanForm onSubmit={vi.fn()} />);
    const help = screen.getByText(/balance after the payment made on the anchor date/i);
    expect(help).toHaveTextContent("first projected payment is one month later");
    for (const label of ["Anchor balance", ANCHOR_DATE]) {
      expect(screen.getByLabelText(label)).toHaveAttribute(
        "aria-describedby",
        expect.stringContaining(help.id),
      );
    }
  });

  it("hides the preview until the fields are valid, then shows payments and payoff date", async () => {
    const user = userEvent.setup();
    render(<LoanForm onSubmit={vi.fn()} />);
    expect(screen.queryByTestId(PREVIEW)).not.toBeInTheDocument();

    await fillValid(user);
    const preview = screen.getByTestId(PREVIEW);
    expect(preview).toHaveTextContent("Remaining payments: 12");
    expect(preview).toHaveTextContent("Projected payoff date: 2026-01-31");
  });

  it("shows the payoff balance when a payoff date truncates the schedule", async () => {
    const user = userEvent.setup();
    render(<LoanForm onSubmit={vi.fn()} />);
    await fillValid(user);
    fireEvent.change(screen.getByLabelText("Payoff date (optional)"), {
      target: { value: "2025-06-30" },
    });
    const preview = screen.getByTestId(PREVIEW);
    expect(preview).toHaveTextContent("Remaining payments: 5");
    expect(preview).toHaveTextContent("Payoff balance: $700.00");
    expect(preview).not.toHaveTextContent("Projected payoff date");
  });

  it.each([
    ["Annual interest rate (%)", "abc"],
    ["Monthly payment (principal and interest)", "0"],
    ["Anchor balance", "x"],
  ])("hides the preview when %s becomes invalid", async (label, bad) => {
    const user = userEvent.setup();
    render(<LoanForm onSubmit={vi.fn()} />);
    await fillValid(user);
    expect(screen.getByTestId(PREVIEW)).toBeInTheDocument();

    const input = screen.getByLabelText(label);
    await user.clear(input);
    await user.type(input, bad);
    expect(screen.queryByTestId(PREVIEW)).not.toBeInTheDocument();
  });

  it("hides the preview when the payment does not exceed the first month's interest", async () => {
    const user = userEvent.setup();
    render(<LoanForm onSubmit={vi.fn()} />);
    await fillValid(user);
    const rate = screen.getByLabelText("Annual interest rate (%)");
    await user.clear(rate);
    await user.type(rate, "12");
    // 1200.00 at 12% is 12.00 interest; 100 still exceeds it.
    expect(screen.getByTestId(PREVIEW)).toBeInTheDocument();
    const payment = screen.getByLabelText("Monthly payment (principal and interest)");
    await user.clear(payment);
    await user.type(payment, "12");
    expect(screen.queryByTestId(PREVIEW)).not.toBeInTheDocument();
  });

  it("shows server field errors and keeps entered values", async () => {
    const user = userEvent.setup();
    render(
      <LoanForm
        onSubmit={vi.fn()}
        serverErrors={{ monthlyPayment: "Server says no.", form: "Request failed." }}
      />,
    );
    await user.type(screen.getByLabelText("Anchor balance"), "500");
    expect(screen.getAllByText("Server says no.")[0]).toBeInTheDocument();
    expect(screen.getByText("Request failed.").closest('[role="alert"]')).not.toBeNull();
    expect(screen.getByLabelText("Anchor balance")).toHaveValue("500");
  });

  it("hides a field's server error when edited and leaves the others", async () => {
    const user = userEvent.setup();
    render(
      <LoanForm
        onSubmit={vi.fn()}
        serverErrors={{
          monthlyPayment: "Payment is bad.",
          anchorBalance: "Balance is bad.",
          form: "Request failed.",
        }}
      />,
    );
    await user.type(screen.getByLabelText("Anchor balance"), "5");
    expect(screen.queryByText("Balance is bad.")).not.toBeInTheDocument();
    expect(screen.getAllByText("Payment is bad.")[0]).toBeInTheDocument();
    expect(screen.getByText("Request failed.").closest('[role="alert"]')).not.toBeNull();
  });

  it("re-shows a dismissed error when a new serverErrors object arrives", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <LoanForm onSubmit={vi.fn()} serverErrors={{ anchorBalance: "Balance is bad." }} />,
    );
    await user.type(screen.getByLabelText("Anchor balance"), "5");
    expect(screen.queryByText("Balance is bad.")).not.toBeInTheDocument();

    rerender(
      <LoanForm onSubmit={vi.fn()} serverErrors={{ anchorBalance: "Balance is bad." }} />,
    );
    expect(screen.getAllByText("Balance is bad.")[0]).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = render(<LoanForm onSubmit={vi.fn()} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("LoanForm - error summary (Req 11.1-11.7)", () => {
  const summaryHeading = () => screen.queryByRole("heading", { level: 2 });

  it("lists every error, focuses the first invalid field, and links focus fields", async () => {
    const user = userEvent.setup();
    render(<LoanForm onSubmit={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Add loan" }));

    expect(summaryHeading()).toHaveTextContent("There are 4 errors");
    expect(screen.getByLabelText("Description")).toHaveFocus();
    // Inline errors still show.
    expect(screen.getByLabelText("Anchor balance")).toHaveAttribute("aria-invalid", "true");

    await user.click(
      screen.getByRole("button", { name: /^Anchor balance must be greater than 0/ }),
    );
    expect(screen.getByLabelText("Anchor balance")).toHaveFocus();
  });

  it("removes the summary once every error is fixed", async () => {
    const user = userEvent.setup();
    render(<LoanForm onSubmit={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Add loan" }));
    expect(summaryHeading()).toBeInTheDocument();

    await user.type(screen.getByLabelText("Description"), "Mortgage");
    await user.type(screen.getByLabelText("Annual interest rate (%)"), "0");
    await user.type(
      screen.getByLabelText("Monthly payment (principal and interest)"),
      "100",
    );
    await user.type(screen.getByLabelText("Anchor balance"), "1200");
    expect(summaryHeading()).not.toBeInTheDocument();
  });

  it("shows a form-level server error in the summary without moving focus", () => {
    render(<LoanForm onSubmit={vi.fn()} serverErrors={{ form: "Request failed." }} />);
    expect(summaryHeading()).toHaveTextContent("There is 1 error");
    expect(screen.getByText("Request failed.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request failed." })).not.toBeInTheDocument();
    expect(document.body).toHaveFocus();
  });

  it("has no axe violations with the summary showing", async () => {
    const user = userEvent.setup();
    const { container } = render(<LoanForm onSubmit={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Add loan" }));
    expect(await axe(container, { rules: { "color-contrast": { enabled: false } } })).toHaveNoViolations();
  });
});
