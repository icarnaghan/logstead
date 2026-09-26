import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { centsToMoney, formatMoney, toCents, toMoneyString } from "./money";

/**
 * Property-based tests for the canonical money helpers (tasks 1.5, 1.6).
 *
 * These exercise the pure money logic across many generated inputs with
 * `fast-check`, complementing the example-based unit tests in `money.test.ts`.
 */

/**
 * Arbitrary generating a well-formed two-decimal money string of the shape
 * `(-)?<digits>.<2 digits>`, e.g. "0.00", "1250.00", "-42.99". Constrained to
 * the exact input space the money model produces so the generators stay
 * meaningful rather than random noise.
 */
const moneyString: fc.Arbitrary<string> = fc
  .tuple(
    fc.boolean(), // negative?
    fc.nat({ max: 99_999_999 }), // whole-dollar part
    fc.integer({ min: 0, max: 99 }), // cents
  )
  .map(([negative, dollars, cents]) => {
    const sign = negative && (dollars > 0 || cents > 0) ? "-" : "";
    const centStr = String(cents).padStart(2, "0");
    return `${sign}${dollars}.${centStr}`;
  });

// Feature: ui-polish-and-visualizations, Property 1: Money formatting preserves exact value
describe("Property 1: Money formatting preserves exact value", () => {
  it("formatted output's dollar-and-cent digits equal the input digits with no rounding", () => {
    fc.assert(
      fc.property(moneyString, (input) => {
        const formatted = formatMoney(input);

        // Strip currency symbol, grouping separators, and sign to compare the
        // raw digit sequence that survived formatting.
        const inputDigits = input.replace(/[-.]/g, "");
        const formattedDigits = formatted.replace(/[^0-9]/g, "");
        expect(formattedDigits).toBe(inputDigits);

        // The sign must be preserved: a negative input formats with a leading
        // minus, and a non-negative input never gains one.
        const inputNegative = input.startsWith("-");
        expect(formatted.startsWith("-")).toBe(inputNegative);
      }),
      { numRuns: 100 },
    );
  });
});

// Feature: ui-polish-and-visualizations, Property 2: Money ↔ integer-cents round-trip (no floating point)
describe("Property 2: Money ↔ integer-cents round-trip (no floating point)", () => {
  it("toCents(s) is an integer and centsToMoney(toCents(s)) equals the normalized form of s", () => {
    fc.assert(
      fc.property(moneyString, (input) => {
        const cents = toCents(input);
        expect(Number.isInteger(cents)).toBe(true);

        // The normalized form of the input is its two-decimal representation.
        // "-0.00" normalizes to "0.00" because negative zero is not a loss.
        const normalized = cents === 0 ? "0.00" : toMoneyString(input);
        expect(centsToMoney(cents)).toBe(normalized);
      }),
      { numRuns: 100 },
    );
  });
});
