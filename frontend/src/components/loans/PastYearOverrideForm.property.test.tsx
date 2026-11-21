import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import fc from "fast-check";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/loans", () => ({
  setInterestOverride: vi.fn(),
}));

import { setInterestOverride } from "../../api/loans";
import { PastYearOverrideForm } from "./PastYearOverrideForm";

// Feature: loan-balance-anchor, Property 24: The add-override form never sends an invalid value
// **Validates: Requirements 11.5, 11.6**

const ANCHOR_YEAR = 2025;

const validYear = fc.integer({ min: 1900, max: ANCHOR_YEAR }).map(String);
const validAmount = fc
  .tuple(
    fc.stringMatching(/^[0-9]{1,8}$/),
    fc.option(fc.stringMatching(/^[0-9]{1,2}$/), { nil: null }),
  )
  .map(([i, f]) => (f === null ? i : `${i}.${f}`));

const isValidYearText = (s: string) => {
  const t = s.trim();
  return /^\d{4}$/.test(t) && Number(t) >= 1900 && Number(t) <= ANCHOR_YEAR;
};
const isValidAmountText = (s: string) => /^\d+(\.\d{1,2})?$/.test(s.trim());

const badYear = fc.oneof(
  fc.integer({ min: 0, max: 1899 }).map(String),
  fc.integer({ min: ANCHOR_YEAR + 1, max: 99999 }).map(String),
  fc.string({ maxLength: 8 }),
  fc.integer({ min: 1, max: 5000 }).map((n) => `-${n}`),
).filter((s) => !isValidYearText(s));

const badAmount = fc.oneof(
  fc.stringMatching(/^[0-9]{1,8}$/).map((d) => `-${d}`),
  fc.string({ maxLength: 12 }),
  fc
    .tuple(fc.stringMatching(/^[0-9]{1,8}$/), fc.stringMatching(/^[0-9]{3,6}$/))
    .map(([i, f]) => `${i}.${f}`),
).filter((s) => !isValidAmountText(s));

function renderForm() {
  return render(
    <PastYearOverrideForm
      propertyId="p1"
      loanId="l1"
      anchorYear={ANCHOR_YEAR}
      yearsWithPayments={[]}
    />,
  );
}

function fill(year: string, amount: string) {
  fireEvent.change(screen.getByLabelText(/tax year/i), { target: { value: year } });
  fireEvent.change(screen.getByLabelText(/form 1098 interest/i), {
    target: { value: amount },
  });
  fireEvent.click(screen.getByRole("button", { name: /add override/i }));
}

describe("PastYearOverrideForm property tests", () => {
  beforeEach(() => {
    vi.mocked(setInterestOverride).mockReset();
  });
  afterEach(cleanup);

  it("Property 24: an invalid year or amount shows a message and never calls the API", () => {
    const cases = fc.oneof(
      fc.tuple(badYear, fc.oneof(validAmount, badAmount)),
      fc.tuple(validYear, badAmount),
    );
    fc.assert(
      fc.property(cases, ([year, amount]) => {
        const { unmount } = renderForm();
        try {
          fill(year, amount);
          const yearBad = !isValidYearText(year);
          const amountBad = !isValidAmountText(amount);
          const alerts = screen.getAllByRole("alert");
          expect(alerts.length).toBe((yearBad ? 1 : 0) + (amountBad ? 1 : 0));
          if (yearBad) {
            expect(screen.getByLabelText(/tax year/i).getAttribute("aria-describedby")).toBeTruthy();
          }
          if (amountBad) {
            expect(
              screen.getByLabelText(/form 1098 interest/i).getAttribute("aria-describedby"),
            ).toBeTruthy();
          }
          expect(setInterestOverride).not.toHaveBeenCalled();
        } finally {
          unmount();
        }
      }),
      { numRuns: 50 },
    );
  });

  it("Property 24: valid values call the API once with the year and the amount unchanged", async () => {
    await fc.assert(
      fc.asyncProperty(validYear, validAmount, async (year, amount) => {
        vi.mocked(setInterestOverride).mockReset();
        vi.mocked(setInterestOverride).mockResolvedValue({
          tax_year: Number(year),
          payments: 0,
          interest: amount,
          estimated_interest: "0.00",
          interest_override: amount,
          variance: null,
          principal: "0.00",
          total_paid: "0.00",
          ending_balance: null,
        });
        const { unmount } = renderForm();
        try {
          fill(year, amount);
          await waitFor(() => expect(setInterestOverride).toHaveBeenCalledTimes(1));
          expect(setInterestOverride).toHaveBeenCalledWith("p1", "l1", Number(year), amount);
          expect(screen.queryAllByRole("alert")).toHaveLength(0);
        } finally {
          unmount();
        }
      }),
      { numRuns: 30 },
    );
  });
});
