import { describe, expect, it } from "vitest";
import fc from "fast-check";
import {
  centsToMoney,
  formatMoney,
  formatMoneyWholeDollars,
  toCents,
  toMoneyString,
} from "./money";

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


// Feature: depreciation-override-and-whole-dollar-display, Property 6:
// Whole-dollar formatter rounds to the nearest dollar, half-up by magnitude,
// sign-preserving, integer-cents only.
describe("Property 6: Whole-dollar formatter rounds to nearest dollar (integer cents)", () => {
  it("matches an independent integer-cents oracle, with no cents shown and the sign preserved", () => {
    fc.assert(
      fc.property(moneyString, (input) => {
        const formatted = formatMoneyWholeDollars(input);

        // Independent oracle computed purely in integer cents (no float).
        const cents = toCents(input);
        const sign = cents < 0 ? -1 : 1;
        const abs = Math.abs(cents);
        let dollars = Math.floor(abs / 100);
        if (abs % 100 >= 50) dollars += 1; // half-up by magnitude, not ceiling
        const rounded = dollars === 0 ? 0 : sign * dollars; // normalize -0
        const expected = rounded.toLocaleString("en-US", {
          style: "currency",
          currency: "USD",
          minimumFractionDigits: 0,
          maximumFractionDigits: 0,
        });
        expect(formatted).toBe(expected);

        // Whole dollars only: no decimal point in the output.
        expect(formatted.includes(".")).toBe(false);

        // Sign preserved: a negative magnitude keeps its minus; a rounded-to-
        // zero value is never shown as "-$0".
        if (rounded < 0) {
          expect(formatted.startsWith("-")).toBe(true);
        } else {
          expect(formatted.startsWith("-")).toBe(false);
        }
      }),
      { numRuns: 100 },
    );
  });
});

describe("formatMoneyWholeDollars negative rounding examples", () => {
  it("never shows -$0 and rounds half-up by magnitude", () => {
    expect(formatMoneyWholeDollars("-0.01")).toBe("$0");
    expect(formatMoneyWholeDollars("-0.49")).toBe("$0");
    expect(formatMoneyWholeDollars("-0.50")).toBe("-$1");
  });
});

// Feature: depreciation-override-and-whole-dollar-display, Property 7:
// Formatter passthrough for empty, null, and non-numeric input.
describe("Property 7: Whole-dollar formatter passthrough", () => {
  it("returns '' for empty/null/undefined", () => {
    for (const v of ["", null, undefined]) {
      expect(formatMoneyWholeDollars(v)).toBe("");
    }
  });

  it("returns non-numeric strings unchanged (same contract as formatMoney)", () => {
    fc.assert(
      fc.property(
        fc.string().filter((s) => s.trim() !== "" && !Number.isFinite(Number(s))),
        (garbage) => {
          expect(formatMoneyWholeDollars(garbage)).toBe(garbage);
        },
      ),
      { numRuns: 100 },
    );
  });
});
