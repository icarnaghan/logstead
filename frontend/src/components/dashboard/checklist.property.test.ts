import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { computeChecklist, hasTransactionData } from "./checklist";
import type { TrendsSeries } from "../../api/dashboard";

const centsToString = (c: number): string => {
  const abs = Math.abs(c);
  const s = `${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
  return c < 0 ? `-${s}` : s;
};

const centsArb = fc
  .integer({ min: -1_000_000, max: 1_000_000 })
  .map((c) => ({ c, s: centsToString(c) }));

// Bias toward zero so both outcomes are well covered.
const maybeZeroArb = fc.oneof(
  { weight: 3, arbitrary: fc.constant({ c: 0, s: "0.00" }) },
  { weight: 1, arbitrary: centsArb },
);

const yearArb = fc.record({
  income: maybeZeroArb,
  expenses: maybeZeroArb,
});

const seriesArb = fc.array(yearArb, { maxLength: 5 });

describe("checklist properties", () => {
  // Feature: ui-polish-and-consistency, Property 23: Checklist count and visibility
  // **Validates: Requirements 24.5, 24.10, 24.11**
  it("Property 23: Checklist count and visibility", () => {
    fc.assert(
      fc.property(
        fc.record({
          hasProperty: fc.boolean(),
          hasTransactions: fc.boolean(),
          hasLoanOrAsset: fc.boolean(),
          visitedReport: fc.boolean(),
        }),
        fc.boolean(),
        (flags, dismissed) => {
          const view = computeChecklist(flags, dismissed);
          const expected = Object.values(flags).filter(Boolean).length;
          expect(view.completed).toBe(expected);
          expect(view.total).toBe(4);
          expect(view.visible).toBe(!dismissed && expected < 4);
        },
      ),
      { numRuns: 100 },
    );
  });

  // Feature: ui-polish-and-consistency, Property 24: Transaction data is detected from the trends series
  // **Validates: Requirements 24.2**
  it("Property 24: Transaction data is detected from the trends series", () => {
    fc.assert(
      fc.property(seriesArb, (rows) => {
        const series: TrendsSeries = {
          years: rows.map((r, i) => ({
            tax_year: 2020 + i,
            total_income: r.income.s,
            total_expenses: r.expenses.s,
            net: "0.00",
            properties: [],
            depreciation_total: "0.00",
          })),
        };
        const expected = rows.some((r) => r.income.c !== 0 || r.expenses.c !== 0);
        expect(hasTransactionData(series)).toBe(expected);
      }),
      { numRuns: 100 },
    );
  });
});
