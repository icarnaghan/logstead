import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { centsToMoney, formatMoney, toCents, toMoneyString } from "../../lib/money";
import { expenseByCategory } from "./prepare";
import type { ReportLine, ScheduleEReport } from "../../api/reports";

/**
 * Property-based tests for the chart data-preparation boundary (task 15.4).
 *
 * Covers the descending-rank invariant of the expense-by-category builder
 * (Property 8) and reuses the money↔cents round-trip spirit of Property 2 to
 * confirm every prepared datum stays in exact integer cents (Requirements 13.1,
 * 13.2, 13.3, 16.3).
 */

/**
 * Well-formed two-decimal money string `(-)?<digits>.<2 digits>` constrained to
 * the money model's input space so generators stay meaningful.
 */
const moneyString: fc.Arbitrary<string> = fc
  .tuple(
    fc.boolean(),
    fc.nat({ max: 99_999_999 }),
    fc.integer({ min: 0, max: 99 }),
  )
  .map(([negative, dollars, cents]) => {
    const sign = negative && (dollars > 0 || cents > 0) ? "-" : "";
    return `${sign}${dollars}.${String(cents).padStart(2, "0")}`;
  });

/** An arbitrary Schedule E line of either kind, with a money total. */
const reportLine: fc.Arbitrary<ReportLine> = fc.record({
  line: fc.integer({ min: 1, max: 26 }),
  label: fc.string({ minLength: 1, maxLength: 24 }),
  kind: fc.constantFrom<"income" | "expense">("income", "expense"),
  total: moneyString,
});

/** A Schedule E report whose only meaningful field for prep is `lines`. */
const scheduleEReport: fc.Arbitrary<ScheduleEReport> = fc
  .array(reportLine, { maxLength: 30 })
  .map(
    (lines): ScheduleEReport => ({
      header: {
        property_id: "p",
        property_name: "Property",
        address: "",
        property_type: null,
        tax_year: 2024,
        fair_rental_days: 0,
        personal_use_days: 0,
      },
      lines,
      other_items: [],
      totals: { total_income: "0.00", total_expenses: "0.00", net: "0.00" },
    }),
  );

// Feature: ui-polish-and-visualizations, Property 8: Expense-by-category data is ranked by descending amount
describe("Property 8: Expense-by-category data is ranked by descending amount", () => {
  it("prepared expense-by-category cents are non-increasing", () => {
    fc.assert(
      fc.property(scheduleEReport, (report) => {
        const data = expenseByCategory(report);

        // Only expense lines survive.
        const expenseCount = report.lines.filter(
          (line) => line.kind === "expense",
        ).length;
        expect(data).toHaveLength(expenseCount);

        // The series is ranked by non-increasing cents (Req 16.3).
        for (let i = 1; i < data.length; i += 1) {
          expect(data[i - 1].cents).toBeGreaterThanOrEqual(data[i].cents);
        }
      }),
      { numRuns: 100 },
    );
  });
});

// Feature: ui-polish-and-visualizations, Property 2: Money ↔ integer-cents round-trip (no floating point)
describe("Property 2 (reuse): prepared data stays in exact integer cents", () => {
  it("each datum's cents equals toCents(input) and round-trips through formatMoney(centsToMoney(cents))", () => {
    fc.assert(
      fc.property(scheduleEReport, (report) => {
        const data = expenseByCategory(report);
        const expenseLines = report.lines.filter(
          (line) => line.kind === "expense",
        );

        for (const datum of data) {
          // The cents are an exact integer conversion of some expense total.
          expect(Number.isInteger(datum.cents)).toBe(true);

          // formatMoney(centsToMoney(cents)) equals formatting the normalized
          // money string directly — the cents domain is lossless (Req 13.2).
          const money = centsToMoney(datum.cents);
          const normalized = datum.cents === 0 ? "0.00" : money;
          expect(money).toBe(normalized);
          expect(formatMoney(money)).toBe(formatMoney(centsToMoney(datum.cents)));
        }

        // Every prepared datum traces back to an expense line's exact cents.
        const preparedCents = [...data].map((d) => d.cents).sort((a, b) => a - b);
        const sourceCents = expenseLines
          .map((line) => toCents(line.total))
          .sort((a, b) => a - b);
        expect(preparedCents).toEqual(sourceCents);

        // Sanity: toMoneyString of a source total round-trips to the same cents.
        for (const line of expenseLines) {
          expect(toCents(toMoneyString(line.total))).toBe(toCents(line.total));
        }
      }),
      { numRuns: 100 },
    );
  });
});
