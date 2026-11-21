import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import fc from "fast-check";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { YearlyRollup } from "../../api/loans";

vi.mock("../../api/loans", () => ({
  setInterestOverride: vi.fn(),
  clearInterestOverride: vi.fn(),
}));

import { clearInterestOverride, setInterestOverride } from "../../api/loans";
import { InterestOverrideControl } from "./InterestOverrideControl";

// Feature: mortgage-amortization, Property 30: Client override validation never sends a bad value
// **Validates: Requirements 9.14**

const rollup: YearlyRollup = {
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

const digits = fc.stringMatching(/^[0-9]{1,8}$/);

const negative = digits.map((d) => `-${d}`);
const nonNumeric = fc
  .string({ minLength: 1, maxLength: 12 })
  .filter((s) => !/^\s*\d+(\.\d{1,2})?\s*$/.test(s));
const tooManyDecimals = fc
  .tuple(digits, fc.stringMatching(/^[0-9]{3,6}$/))
  .map(([i, f]) => `${i}.${f}`);

const badInput = fc.oneof(negative, nonNumeric, tooManyDecimals);

describe("InterestOverrideControl property tests", () => {
  beforeEach(() => {
    vi.mocked(setInterestOverride).mockReset();
    vi.mocked(clearInterestOverride).mockReset();
  });
  afterEach(cleanup);

  it("Property 30: a bad value shows a message and never calls the API", () => {
    fc.assert(
      fc.property(badInput, (value) => {
        const { unmount } = render(
          <InterestOverrideControl propertyId="p1" loanId="l1" rollup={rollup} />,
        );
        try {
          const input = screen.getByRole("textbox");
          fireEvent.change(input, { target: { value } });
          fireEvent.click(screen.getByRole("button", { name: /save interest override/i }));
          expect(screen.getByRole("alert").textContent).toMatch(/at most two decimal/i);
          expect(input.getAttribute("aria-describedby")).toBe(
            screen.getByRole("alert").id,
          );
          expect(setInterestOverride).not.toHaveBeenCalled();
        } finally {
          unmount();
        }
      }),
      { numRuns: 50 },
    );
  });
});
