import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import {
  formatMoneyDisplay,
  parseMoneyDisplay,
  sanitizeMoneyInput,
} from "./moneyInput";
import { centsToMoney } from "./money";

const GRAMMAR = /^-?\d*(\.\d{0,2})?$/;

// Mix of arbitrary text and money-flavoured characters to hit edge cases.
const rawText = fc.oneof(
  fc.string({ maxLength: 40 }),
  fc.stringMatching(/^[0-9.,$\-\sa-z]{0,40}$/),
);

describe("moneyInput properties", () => {
  // Feature: ui-polish-and-consistency, Property 6: Sanitized money text always fits the grammar
  /** **Validates: Requirements 12.3, 12.5** */
  it("Property 6: sanitized money text always fits the grammar", () => {
    fc.assert(
      fc.property(rawText, fc.boolean(), (raw, allowNegative) => {
        const out = sanitizeMoneyInput(raw, { allowNegative });
        expect(out).toMatch(GRAMMAR);
        if (!allowNegative) expect(out.startsWith("-")).toBe(false);
        expect(sanitizeMoneyInput(out, { allowNegative })).toBe(out);
      }),
      { numRuns: 100 },
    );
  });

  // Feature: ui-polish-and-consistency, Property 7: Pasted decorated amounts keep their numeric value
  /** **Validates: Requirements 12.4** */
  it("Property 7: pasted decorated amounts keep their numeric value", () => {
    const canonical = fc
      .tuple(
        fc.boolean(),
        fc.integer({ min: 0, max: 999_999_999 }),
        fc.integer({ min: 0, max: 99 }),
      )
      .map(([neg, whole, cents]) => ({
        neg,
        whole: String(whole),
        value: `${neg ? "-" : ""}${whole}.${String(cents).padStart(2, "0")}`,
        cents: String(cents).padStart(2, "0"),
      }));

    fc.assert(
      fc.property(canonical, fc.boolean(), (c, symbolAfterMinus) => {
        const grouped = c.whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        const body = `$${grouped}.${c.cents}`;
        const decorated = c.neg
          ? symbolAfterMinus
            ? `-${body}`
            : `$-${grouped}.${c.cents}`
          : body;
        expect(sanitizeMoneyInput(decorated, { allowNegative: true })).toBe(
          c.value,
        );
      }),
      { numRuns: 100 },
    );
  });

  // Feature: ui-polish-and-consistency, Property 8: Money format and parse round trip
  /** **Validates: Requirements 12.6, 12.7** */
  it("Property 8: money format and parse round trip", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: -99_999_999_999, max: 99_999_999_999 }),
        (cents) => {
          const c = centsToMoney(cents);
          expect(
            parseMoneyDisplay(formatMoneyDisplay(c), { allowNegative: true }),
          ).toBe(c);
        },
      ),
      { numRuns: 100 },
    );
  });
});
