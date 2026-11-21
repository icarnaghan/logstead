import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DateInput } from "./DateInput";

/** DateInput behavior (task 14.8, Requirements 12.8, 12.9). */

function Harness({ showToday }: { showToday?: boolean }) {
  const [value, setValue] = useState("");
  return (
    <DateInput
      aria-label="Date"
      value={value}
      onValueChange={setValue}
      showToday={showToday}
    />
  );
}

describe("DateInput", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    // Local time (no Z): late evening, where toISOString would roll forward in UTC+ zones.
    vi.setSystemTime(new Date(2024, 2, 9, 23, 30, 0));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders a date input", () => {
    render(<Harness />);
    expect(screen.getByLabelText("Date")).toHaveAttribute("type", "date");
  });

  it("Today sets the local date and focuses the input", () => {
    render(<Harness />);
    const input = screen.getByLabelText("Date");
    fireEvent.click(screen.getByRole("button", { name: "Today" }));
    expect(input).toHaveValue("2024-03-09");
    expect(input).toHaveFocus();
  });

  it("omits the Today button when showToday is false", () => {
    render(<Harness showToday={false} />);
    expect(screen.queryByRole("button", { name: "Today" })).toBeNull();
  });

  it("has no axe violations", async () => {
    const { container } = render(<Harness />);
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
