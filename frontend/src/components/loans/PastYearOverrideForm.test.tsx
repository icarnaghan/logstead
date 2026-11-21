import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { YearlyRollup } from "../../api/loans";

vi.mock("../../api/loans", () => ({
  setInterestOverride: vi.fn(),
}));

import { setInterestOverride } from "../../api/loans";
import { ApiError } from "../../lib/apiClient";
import { PastYearOverrideForm } from "./PastYearOverrideForm";

const saved: YearlyRollup = {
  tax_year: 2023,
  payments: 0,
  interest: "20650.12",
  estimated_interest: "0.00",
  interest_override: "20650.12",
  variance: "20650.12",
  principal: "0.00",
  total_paid: "0.00",
  ending_balance: null,
};

function setup(onSaved = vi.fn()) {
  render(
    <PastYearOverrideForm
      propertyId="p1"
      loanId="l1"
      anchorYear={2025}
      yearsWithPayments={[2025, 2026]}
      onSaved={onSaved}
    />,
  );
  return onSaved;
}

function fill(year: string, amount: string) {
  fireEvent.change(screen.getByLabelText("Tax year"), { target: { value: year } });
  fireEvent.change(screen.getByLabelText("Form 1098 interest"), { target: { value: amount } });
  fireEvent.click(screen.getByRole("button", { name: "Add override" }));
}

describe("PastYearOverrideForm", () => {
  beforeEach(() => {
    vi.mocked(setInterestOverride).mockReset();
  });
  afterEach(cleanup);

  it("saves a valid year and amount and reports the result", async () => {
    vi.mocked(setInterestOverride).mockResolvedValue(saved);
    const onSaved = setup();
    fill("2023", "20650.12");
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
    expect(setInterestOverride).toHaveBeenCalledWith("p1", "l1", 2023, "20650.12");
  });

  it.each(["1899", "2026", "20x3", ""])("rejects year %j without calling the API", (year) => {
    setup();
    fill(year, "100");
    expect(screen.getByRole("alert").textContent).toContain("from 1900 to 2025");
    expect(setInterestOverride).not.toHaveBeenCalled();
  });

  it.each(["-5", "abc", "1.234", ""])("rejects amount %j without calling the API", (amount) => {
    setup();
    fill("2023", amount);
    expect(screen.getByRole("alert").textContent).toContain("non-negative amount");
    expect(setInterestOverride).not.toHaveBeenCalled();
  });

  it("points to the row control when the year has payments", () => {
    setup();
    fill("2025", "100");
    expect(screen.getByRole("alert").textContent).toContain("has payments");
    expect(setInterestOverride).not.toHaveBeenCalled();
  });

  it("shows a server year error next to the year field", async () => {
    vi.mocked(setInterestOverride).mockImplementation(async () => {
      throw new ApiError(422, "Unprocessable", {
        field: "interest_overrides.2023",
        message: "Tax year is not allowed.",
      });
    });
    setup();
    fill("2023", "100");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Tax year is not allowed.");
    expect(screen.getByLabelText("Tax year").getAttribute("aria-describedby")).toBe(alert.id);
  });
});
