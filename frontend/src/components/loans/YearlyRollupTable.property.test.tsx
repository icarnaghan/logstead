import {
  cleanup,
  fireEvent,
  render,
  within,
} from "@testing-library/react";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { YearlyRollupTable } from "./YearlyRollupTable";
import type { LoanSchedule, PaymentRow, YearlyRollup } from "../../api/loans";
import {
  centsToMoney,
  formatMoney,
  formatMoneyWholeDollars,
} from "../../lib/money";

/**
 * Property test for the yearly rollup table (task 16.7).
 * Money is generated from integer cents and rendered to strings with
 * centsToMoney; no floats are involved.
 */

// Feature: loan-balance-anchor, Property 23: Yearly table formatting including override-only rows
// **Validates: Requirements 11.2, 11.3**

const cents = fc.integer({ min: 0, max: 99_999_999_999 });
const money = cents.map(centsToMoney);

const paymentFor = (year: number, number: number) =>
  fc
    .record({
      month: fc.integer({ min: 1, max: 12 }),
      payment: money,
      interest: money,
      principal: money,
      balance: money,
    })
    .map(
      (r): PaymentRow => ({
        number,
        date: `${year}-${String(r.month).padStart(2, "0")}-01`,
        payment: r.payment,
        interest: r.interest,
        principal: r.principal,
        balance: r.balance,
      }),
    );

const yearRow = (taxYear: number) =>
  fc
    .record({
      payments: fc.integer({ min: 0, max: 12 }),
      interest: money,
      principal: money,
      total_paid: money,
      ending_balance: money,
    })
    .map(
      (r): YearlyRollup => ({
        tax_year: taxYear,
        payments: r.payments,
        interest: r.interest,
        estimated_interest: r.interest,
        interest_override: null,
        variance: null,
        principal: r.principal,
        total_paid: r.total_paid,
        ending_balance: r.payments === 0 ? null : r.ending_balance,
      }),
    );

const scheduleArb: fc.Arbitrary<LoanSchedule> = fc
  .uniqueArray(fc.integer({ min: 1990, max: 2090 }), {
    minLength: 1,
    maxLength: 5,
  })
  .chain((years) =>
    fc.tuple(
      fc.tuple(...years.map((y) => yearRow(y))),
      fc.tuple(
        ...years.map((y, i) =>
          fc.array(fc.constant(0), { minLength: 1, maxLength: 3 }).chain((arr) =>
            fc.tuple(...arr.map((_, j) => paymentFor(y, i * 10 + j + 1))),
          ),
        ),
      ),
    ),
  )
  .map(([yearly, paymentGroups]) => ({
    loan_id: "loan-1",
    estimate: true,
    payoff_balance: null,
    // Input order is as generated (unsorted); the table must sort ascending.
    yearly,
    payments: paymentGroups
      .flat()
      .filter((p) =>
        yearly.some(
          (y) => y.payments > 0 && p.date.startsWith(`${y.tax_year}-`),
        ),
      ),
  }));

describe("Property 23: Yearly table formatting including override-only rows", () => {
  it("renders one row per year ascending with whole-dollar money, and expanded payments to the cent", () => {
    fc.assert(
      fc.property(scheduleArb, (schedule) => {
        const { container } = render(
          <YearlyRollupTable caption="Loan" schedule={schedule} />,
        );
        try {
          // First table is the outer one; ResponsiveTable also renders cards.
          const table = container.querySelector("table") as HTMLElement;
          const rows = Array.from(
            table.querySelectorAll(":scope > tbody > tr:not([id])"),
          );
          const expected = [...schedule.yearly].sort(
            (a, b) => a.tax_year - b.tax_year,
          );
          expect(rows).toHaveLength(expected.length);

          expected.forEach((y, i) => {
            const cells = Array.from(rows[i].children).map((c) =>
              (c.textContent ?? "").trim(),
            );
            expect(cells[1]).toBe(formatMoneyWholeDollars(y.interest));
            if (y.payments === 0) {
              expect(cells[0].startsWith(String(y.tax_year))).toBe(true);
              expect(cells[0]).toContain("Override only");
              expect(cells.slice(2, 5)).toEqual(["\u2014", "\u2014", "\u2014"]);
              expect(cells[5]).toBe("");
            } else {
              expect(cells[0]).toBe(String(y.tax_year));
              expect(cells[2]).toBe(formatMoneyWholeDollars(y.principal));
              expect(cells[3]).toBe(formatMoneyWholeDollars(y.total_paid));
              expect(cells[4]).toBe(
                formatMoneyWholeDollars(y.ending_balance as string),
              );
            }
          });

          // Only years with payments get an expand control.
          expect(within(table).queryAllByRole("button")).toHaveLength(
            expected.filter((y) => y.payments > 0).length,
          );

          // Expand every year and check each payment row.
          for (const button of within(table).queryAllByRole("button")) {
            fireEvent.click(button);
          }
          for (const y of expected.filter((y) => y.payments > 0)) {
            const panel = container.querySelector(
              `#loan-loan-1-year-${y.tax_year}-payments`,
            ) as HTMLElement;
            const payRows = Array.from(panel.querySelectorAll("tbody > tr"));
            const mine = schedule.payments.filter((p) =>
              p.date.startsWith(`${y.tax_year}-`),
            );
            expect(payRows).toHaveLength(mine.length);
            mine.forEach((p, i) => {
              const cells = Array.from(payRows[i].children).map((c) =>
                (c.textContent ?? "").trim(),
              );
              expect(cells).toEqual([
                String(p.number),
                p.date,
                formatMoney(p.payment),
                formatMoney(p.interest),
                formatMoney(p.principal),
                formatMoney(p.balance),
              ]);
            });
          }
        } finally {
          cleanup();
        }
      }),
      { numRuns: 50 },
    );
  }, 60_000);
});
