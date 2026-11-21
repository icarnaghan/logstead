import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { MoneyInput } from "./MoneyInput";

/** MoneyInput behavior (task 14.8, Requirements 12.1-12.6). */

function Harness({
  initial = "",
  allowNegative,
}: {
  initial?: string;
  allowNegative?: boolean;
}) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <MoneyInput
        aria-label="Amount"
        value={value}
        onValueChange={setValue}
        allowNegative={allowNegative}
      />
      <output data-testid="canonical">{value}</output>
    </>
  );
}

const canonical = () => screen.getByTestId("canonical").textContent;

describe("MoneyInput", () => {
  it("renders a hidden $ prefix and a decimal keypad", () => {
    const { container } = render(<Harness />);
    const input = screen.getByLabelText("Amount");
    expect(input).toHaveAttribute("inputmode", "decimal");
    expect(input).toHaveAttribute("type", "text");
    const prefix = container.querySelector("span[aria-hidden='true']");
    expect(prefix).toHaveTextContent("$");
  });

  it("rejects letters", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("Amount"), "12abc3");
    expect(canonical()).toBe("123");
  });

  it("strips a pasted '$1,250.00'", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByLabelText("Amount"));
    await user.paste("$1,250.00");
    expect(canonical()).toBe("1250.00");
    expect(screen.getByLabelText("Amount")).toHaveValue("1250.00");
  });

  it("limits decimals to two digits", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("Amount"), "1.2345");
    expect(canonical()).toBe("1.23");
  });

  it("rejects a minus sign unless negatives are allowed", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<Harness />);
    await user.type(screen.getByLabelText("Amount"), "-5");
    expect(canonical()).toBe("5");
    unmount();

    render(<Harness allowNegative />);
    await user.type(screen.getByLabelText("Amount"), "-5");
    expect(canonical()).toBe("-5");
  });

  it("formats on blur and shows canonical text on focus", async () => {
    const user = userEvent.setup();
    render(<Harness initial="1250.5" />);
    const input = screen.getByLabelText("Amount");
    // Not focused: formatted display.
    expect(input).toHaveValue("1,250.50");

    await user.click(input);
    expect(input).toHaveValue("1250.5");

    await user.tab();
    expect(input).toHaveValue("1,250.50");
    expect(canonical()).toBe("1250.50");
  });

  it("has no axe violations", async () => {
    const { container } = render(<Harness initial="10" />);
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
