import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { YearlyRollup } from "../../api/loans";

vi.mock("../../api/loans", () => ({
  setInterestOverride: vi.fn(),
  clearInterestOverride: vi.fn(),
}));

import { clearInterestOverride, setInterestOverride } from "../../api/loans";
import { ApiError } from "../../lib/apiClient";
import { InterestOverrideControl, varianceText } from "./InterestOverrideControl";

const base: YearlyRollup = {
  tax_year: 2024,
  payments: 12,
  interest: "7000.00",
  estimated_interest: "7000.00",
  interest_override: null,
  variance: null,
  principal: "3000.00",
  total_paid: "10000.00",
  ending_balance: "200000.00",
};

const overridden: YearlyRollup = {
  ...base,
  interest: "6880.00",
  interest_override: "6880.00",
  variance: "-120.00",
};

describe("InterestOverrideControl", () => {
  beforeEach(() => {
    vi.mocked(setInterestOverride).mockReset();
    vi.mocked(clearInterestOverride).mockReset();
  });
  afterEach(cleanup);

  it("saves the typed value with the Save button and reports the result", async () => {
    vi.mocked(setInterestOverride).mockResolvedValue(overridden);
    const onChange = vi.fn();
    render(<InterestOverrideControl propertyId="p1" loanId="l1" rollup={base} onChange={onChange} />);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "6880.00" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save interest override for 2024/i }));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(overridden));
    expect(setInterestOverride).toHaveBeenCalledWith("p1", "l1", 2024, "6880.00");
  });

  it("saves on Enter but not on blur", async () => {
    vi.mocked(setInterestOverride).mockResolvedValue(overridden);
    render(<InterestOverrideControl propertyId="p1" loanId="l1" rollup={base} />);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "6880" } });
    fireEvent.blur(input);
    expect(setInterestOverride).not.toHaveBeenCalled();
    fireEvent.submit(input.closest("form")!);
    await waitFor(() => expect(setInterestOverride).toHaveBeenCalledWith("p1", "l1", 2024, "6880"));
  });

  it("states the variance in words when an override exists", () => {
    render(<InterestOverrideControl propertyId="p1" loanId="l1" rollup={overridden} />);
    expect(screen.getByText("$120 lower than the estimate")).toBeTruthy();
  });

  it("states a higher variance in words", () => {
    expect(varianceText("45.00")).toBe("$45 higher than the estimate");
  });

  it("clears the override and reports the result", async () => {
    vi.mocked(clearInterestOverride).mockResolvedValue(base);
    const onChange = vi.fn();
    render(<InterestOverrideControl propertyId="p1" loanId="l1" rollup={overridden} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /clear interest override for 2024/i }));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(base));
    expect(clearInterestOverride).toHaveBeenCalledWith("p1", "l1", 2024);
  });

  it("disables Clear when there is no override", () => {
    render(<InterestOverrideControl propertyId="p1" loanId="l1" rollup={base} />);
    const clear = screen.getByRole("button", { name: /clear interest override for 2024/i });
    expect((clear as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows a server field error next to the year", async () => {
    vi.mocked(setInterestOverride).mockRejectedValue(
      new ApiError(422, "Unprocessable", {
        field: "interest_overrides.2024",
        message: "Interest cannot exceed total paid.",
      }),
    );
    render(<InterestOverrideControl propertyId="p1" loanId="l1" rollup={base} />);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "99999" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save interest override/i }));
    expect((await screen.findByRole("alert")).textContent).toBe("Interest cannot exceed total paid.");
  });
});
