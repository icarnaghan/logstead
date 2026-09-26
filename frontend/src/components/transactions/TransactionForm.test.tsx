import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import type { Category, TransactionInput } from "../../api/transactions";
import { TransactionForm } from "./TransactionForm";

/**
 * Component tests for the transaction create/edit form in isolation (task 22.3).
 *
 * These deepen coverage beyond the page-level tests: category options filter by
 * income vs. expense and reset on a type switch, the selected category surfaces
 * its Schedule E line, the "Other" (Line 19) category requires a description,
 * non-positive/invalid amounts are blocked, amounts are normalized to two
 * decimals in the submit payload, and a server field error renders next to the
 * right control.
 *
 * Validates: Requirements 5.1, 5.2, 5.3, 7.3, 7.4, 14.3
 */

const CATEGORIES: Category[] = [
  {
    id: "rents",
    kind: "income",
    label: "Rents received",
    schedule_e_line: "3",
    requires_description: false,
  },
  {
    id: "royalties",
    kind: "income",
    label: "Royalties received",
    schedule_e_line: "4",
    requires_description: false,
  },
  {
    id: "repairs",
    kind: "expense",
    label: "Repairs",
    schedule_e_line: "14",
    requires_description: false,
  },
  {
    id: "other",
    kind: "expense",
    label: "Other",
    schedule_e_line: "19",
    requires_description: true,
  },
];

function setup(props: Partial<React.ComponentProps<typeof TransactionForm>> = {}) {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  const user = userEvent.setup();
  render(
    <TransactionForm
      categories={CATEGORIES}
      taxYear={2026}
      onSubmit={onSubmit}
      onCancel={onCancel}
      {...props}
    />,
  );
  return { user, onSubmit, onCancel };
}

/** The category `<select>` (labelled "Category"). */
function categorySelect(): HTMLSelectElement {
  return screen.getByLabelText(/^category$/i) as HTMLSelectElement;
}

describe("TransactionForm", () => {
  it("offers only expense categories by default and switches to income options", async () => {
    const { user } = setup();

    // Default type is expense: only expense categories are offered.
    expect(
      screen.getByRole("option", { name: /repairs/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /other/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: /rents received/i }),
    ).not.toBeInTheDocument();

    // Switching to income swaps the option set.
    await user.click(screen.getByRole("radio", { name: /income/i }));
    expect(
      screen.getByRole("option", { name: /rents received/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: /repairs/i }),
    ).not.toBeInTheDocument();
  });

  it("resets the selected category when the type changes", async () => {
    const { user } = setup();

    await user.selectOptions(categorySelect(), "repairs");
    expect(categorySelect().value).toBe("repairs");

    // Flipping the type clears the (now-invalid) category selection.
    await user.click(screen.getByRole("radio", { name: /income/i }));
    expect(categorySelect().value).toBe("");
  });

  it("shows the Schedule E line for the selected category (Requirement 7.3)", async () => {
    const { user } = setup();

    await user.selectOptions(categorySelect(), "repairs");
    expect(screen.getByText(/schedule e line 14/i)).toBeInTheDocument();

    await user.selectOptions(categorySelect(), "other");
    expect(screen.getByText(/schedule e line 19/i)).toBeInTheDocument();
  });

  it("blocks submit for the Other category without a description, then allows it (Requirement 7.4)", async () => {
    const { user, onSubmit } = setup();

    await user.type(screen.getByLabelText(/amount/i), "50");
    await user.selectOptions(categorySelect(), "other");
    await user.click(screen.getByRole("button", { name: /add transaction/i }));

    // Missing description blocks submit and surfaces a field error.
    expect(onSubmit).not.toHaveBeenCalled();
    expect(
      screen.getByText(/a description is required for the other category/i),
    ).toBeInTheDocument();

    // Supplying a description clears the block and submits.
    await user.type(screen.getByLabelText(/description/i), "Bank fees");
    await user.click(screen.getByRole("button", { name: /add transaction/i }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const payload = onSubmit.mock.calls[0][0] as TransactionInput;
    expect(payload).toMatchObject({
      category_id: "other",
      description: "Bank fees",
      type: "expense",
      // Date is hidden and defaults to Dec 31 of the selected tax year.
      date: "2026-12-31",
    });
  });

  it("blocks submit for a non-positive or invalid amount with a field error (Requirement 5.2)", async () => {
    const { user, onSubmit } = setup();

    await user.selectOptions(categorySelect(), "repairs");
    await user.type(screen.getByLabelText(/amount/i), "0");
    await user.click(screen.getByRole("button", { name: /add transaction/i }));

    expect(onSubmit).not.toHaveBeenCalled();
    const amountInput = screen.getByLabelText(/amount/i);
    expect(amountInput).toHaveAttribute("aria-invalid", "true");
    expect(
      screen.getByText(/amount must be a number greater than zero/i),
    ).toBeInTheDocument();
  });

  it("normalizes the amount to two decimals in the submit payload (Requirement 13.3)", async () => {
    const { user, onSubmit } = setup();

    await user.selectOptions(categorySelect(), "repairs");
    await user.type(screen.getByLabelText(/amount/i), "99.9");
    await user.click(screen.getByRole("button", { name: /add transaction/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const payload = onSubmit.mock.calls[0][0] as TransactionInput;
    expect(payload.amount).toBe("99.90");
  });

  it("renders a server field error next to the offending control (Requirement 14.3)", () => {
    setup({ serverError: { field: "amount", message: "Amount was rejected by the server." } });

    const amountInput = screen.getByLabelText(/amount/i);
    expect(amountInput).toHaveAttribute("aria-invalid", "true");
    const error = screen.getByText(/amount was rejected by the server/i);
    expect(error).toBeInTheDocument();
    // The message is wired to the amount input for assistive tech.
    expect(amountInput).toHaveAttribute("aria-describedby", "tx-amount-error");
    expect(error).toHaveAttribute("id", "tx-amount-error");
  });

  it("has no automated accessibility violations", async () => {
    const { container } = render(
      <TransactionForm
        categories={CATEGORIES}
        taxYear={2026}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
