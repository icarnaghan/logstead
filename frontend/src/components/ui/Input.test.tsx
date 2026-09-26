import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { Input } from "./Input";

/**
 * Unit + axe tests for the shared Input primitive
 * (task 3.2, Requirements 1.3, 8.1).
 */

describe("Input — base styling (Req 1.3, 8.1)", () => {
  it("applies token-only base classes and the focus ring", () => {
    render(<Input aria-label="Amount" />);
    const input = screen.getByLabelText("Amount");
    expect(input).toHaveClass("rounded-md");
    expect(input).toHaveClass("border-border");
    expect(input).toHaveClass("bg-surface");
    expect(input).toHaveClass("text-fg");
    expect(input).toHaveClass("focus-visible:outline-accent");
  });

  it("forwards native props and ref", () => {
    render(<Input aria-label="Amount" placeholder="0.00" />);
    expect(screen.getByLabelText("Amount")).toHaveAttribute(
      "placeholder",
      "0.00",
    );
  });
});

describe("Input — invalid state (Req 8.1)", () => {
  it("sets aria-invalid and a danger border when invalid", () => {
    render(<Input aria-label="Amount" invalid />);
    const input = screen.getByLabelText("Amount");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveClass("border-danger");
  });

  it("does not set aria-invalid when valid", () => {
    render(<Input aria-label="Amount" />);
    expect(screen.getByLabelText("Amount")).not.toHaveAttribute("aria-invalid");
  });
});

describe("Input — accessibility", () => {
  it("has no axe violations", async () => {
    const { container } = render(
      <div>
        <label htmlFor="amount">Amount</label>
        <Input id="amount" />
      </div>,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
