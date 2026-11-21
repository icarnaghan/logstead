import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  deltaCents,
  describeChange,
  syncLabel,
  syncVisible,
} from "./itemizedMath";
import { centsToMoney, sumMoney } from "./money";

// Feature: itemized-expenses, Property 17: The page's displayed amounts match the integer-cents oracle
// **Validates: Requirements 7.2, 7.3, 9.1, 9.2, 9.3, 14.2**

/** Independent oracle formatter: integer cents to "-$1,234.56" without Intl. */
function oracleMoney(cents: number): string {
  const abs = Math.abs(cents);
  const dollars = String(Math.floor(abs / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const frac = String(abs % 100).padStart(2, "0");
  return `${cents < 0 ? "-" : ""}$${dollars}.${frac}`;
}

const entryCents = fc.integer({ min: 1, max: 10_000_000_00 });
const entries = fc.array(entryCents, { maxLength: 30 });
const totalCents = fc.option(fc.integer({ min: 1, max: 100_000_000_00 }), {
  nil: null,
});

describe("Property 17: itemizedMath matches the integer-cents oracle", () => {
  it("sum, visibility, label, and delta equal integer-cent values", () => {
    fc.assert(
      fc.property(entries, totalCents, (list, total) => {
        const oracleSum = list.reduce((a, b) => a + b, 0);
        const sumStr = sumMoney(list.map(centsToMoney));
        expect(sumStr).toBe(centsToMoney(oracleSum));

        const totalStr = total === null ? null : centsToMoney(total);
        const expectedVisible =
          total !== null && list.length > 0 && total !== oracleSum;
        expect(syncVisible(totalStr, sumStr, list.length)).toBe(expectedVisible);

        expect(syncLabel(sumStr)).toBe(
          `Update total to ${oracleMoney(oracleSum)} (itemized)`,
        );

        if (total !== null) {
          const delta = oracleSum - total;
          expect(deltaCents(centsToMoney(total), sumStr)).toBe(delta);
          const sign = delta > 0 ? "+" : "";
          const text = describeChange({
            label: "Repairs",
            line: 14,
            taxYear: 2024,
            enteredTotal: centsToMoney(total),
            itemizedSum: sumStr,
            itemizedCount: list.length,
          });
          expect(text).toContain(
            `from ${oracleMoney(total)} to ${oracleMoney(oracleSum)} (${sign}${oracleMoney(delta)})`,
          );
        }
      }),
      { numRuns: 200 },
    );
  });
});
