import { cleanup, render, screen, within } from "@testing-library/react";
import fc from "fast-check";
import { afterEach, describe, expect, it } from "vitest";
import type { Line12ImpactYear } from "../../api/loans";
import { formatMoneyWholeDollars } from "../../lib/money";
import { SupersededInterestNotice } from "./SupersededInterestNotice";

// Feature: mortgage-amortization, Property 31: Superseded-interest notice content
// **Validates: Requirements 9.16**

/** Integer cents rendered as a two-decimal money string. */
function centsToString(cents: number): string {
  const whole = Math.floor(cents / 100);
  const frac = String(cents % 100).padStart(2, "0");
  return `${whole}.${frac}`;
}

const cents = fc.integer({ min: 0, max: 99_999_999_99 });

const impactYears = fc
  .uniqueArray(fc.integer({ min: 1990, max: 2100 }), { minLength: 0, maxLength: 8 })
  .chain((taxYears) =>
    fc.tuple(
      ...taxYears.map((tax_year) =>
        fc
          .tuple(cents, cents, fc.integer({ min: 0, max: 500 }))
          .map(
            ([loan, manual, count]): Line12ImpactYear => ({
              tax_year,
              loan_interest: centsToString(loan),
              superseded_manual_interest: { amount: centsToString(manual), count },
            }),
          ),
      ),
    ),
  );

describe("SupersededInterestNotice property tests", () => {
  afterEach(cleanup);

  it("Property 31: one notice per year with tax year, whole-dollar amount, and restore instruction", () => {
    fc.assert(
      fc.property(impactYears, (years) => {
        const { container, unmount } = render(<SupersededInterestNotice years={years} />);
        try {
          if (years.length === 0) {
            expect(container.firstChild).toBeNull();
            return;
          }
          const notices = screen.getAllByRole("note");
          expect(notices).toHaveLength(years.length);
          years.forEach((year, i) => {
            const text = notices[i].textContent ?? "";
            expect(text).toContain(`Tax year ${year.tax_year}`);
            expect(text).toContain(
              formatMoneyWholeDollars(year.superseded_manual_interest.amount),
            );
            expect(text).toMatch(/turn report_inclusion off/i);
            expect(text).toMatch(/restore the manual figures/i);
            expect(within(notices[i]).queryByText(/\.\d{2}\b/)).toBeNull();
          });
        } finally {
          unmount();
        }
      }),
      { numRuns: 50 },
    );
  });
});
