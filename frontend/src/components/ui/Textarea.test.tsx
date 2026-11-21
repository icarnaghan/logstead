import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { Input } from "./Input";
import { Textarea } from "./Textarea";

/** Textarea parity with Input (task 6.4, Requirements 6.1, 6.4, 6.7). */

describe("Textarea", () => {
  it("shares Input's base and focus classes", () => {
    render(
      <>
        <Input aria-label="I" />
        <Textarea aria-label="T" />
      </>,
    );
    const input = screen.getByLabelText("I");
    const textarea = screen.getByLabelText("T");
    for (const cls of [
      "rounded-md",
      "border-border-strong",
      "bg-surface",
      "text-fg",
      "max-md:min-h-11",
      "focus-visible:outline-accent",
    ]) {
      expect(input).toHaveClass(cls);
      expect(textarea).toHaveClass(cls);
    }
  });

  it("sets aria-invalid and danger border only when invalid", () => {
    const { rerender } = render(<Textarea aria-label="T" />);
    expect(screen.getByLabelText("T")).not.toHaveAttribute("aria-invalid");
    rerender(<Textarea aria-label="T" invalid />);
    const el = screen.getByLabelText("T");
    expect(el).toHaveAttribute("aria-invalid", "true");
    expect(el).toHaveClass("border-danger");
  });

  it("forwards native props", () => {
    render(<Textarea aria-label="T" rows={4} placeholder="Notes" />);
    expect(screen.getByLabelText("T")).toHaveAttribute("rows", "4");
  });

  it("has no axe violations", async () => {
    const { container } = render(
      <div>
        <label htmlFor="t">Notes</label>
        <Textarea id="t" />
      </div>,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
