import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { parseYearParam } from "../../lib/taxYears";
import {
  NO_PROPERTY_REASON,
  resolveActionTarget,
  type PropertyScopedActionId,
} from "./paletteItems";

const SEGMENTS: Record<PropertyScopedActionId, string> = {
  "add-transaction": "transactions",
  "add-repair": "repairs",
  "add-asset": "assets",
  "add-loan": "loans",
};

const actionArb = fc.constantFrom<PropertyScopedActionId>(
  "add-transaction",
  "add-repair",
  "add-asset",
  "add-loan",
);
const idArb = fc.stringMatching(/^[a-z0-9-]{1,12}$/);
const propsArb = fc
  .uniqueArray(idArb, { maxLength: 5 })
  .map((ids) => ids.map((id) => ({ id })));

describe("Property 6: Year parameter parsing", () => {
  /** **Validates: Requirements 2.5, 2.6** */
  it("accepts canonical years 1900 through 2200", () => {
    fc.assert(
      fc.property(fc.integer({ min: 1900, max: 2200 }), (year) => {
        expect(parseYearParam(String(year))).toBe(year);
      }),
    );
  });

  it("returns an integer only for the canonical form of 1900 through 2200", () => {
    fc.assert(
      fc.property(fc.string(), (s) => {
        const result = parseYearParam(s);
        const n = Number(s);
        const canonical =
          s.trim() === s &&
          s !== "" &&
          Number.isInteger(n) &&
          n >= 1900 &&
          n <= 2200 &&
          String(n) === s;
        expect(result).toBe(canonical ? n : null);
      }),
    );
  });

  it("rejects non-canonical and out-of-range forms", () => {
    fc.assert(
      fc.property(
        fc.oneof(
          fc.integer({ min: 0, max: 1899 }).map(String),
          fc.integer({ min: 2201, max: 99999 }).map(String),
          fc.integer({ min: 1900, max: 2200 }).map((y) => ` ${y}`),
          fc.integer({ min: 1900, max: 2200 }).map((y) => `${y} `),
          fc.integer({ min: 1900, max: 2200 }).map((y) => `+${y}`),
          fc.integer({ min: 1900, max: 2200 }).map((y) => `0${y}`),
          fc.integer({ min: 1900, max: 2200 }).map((y) => `${y}.0`),
          fc.integer({ min: 1900, max: 2200 }).map((y) => `${y}e0`),
          fc.constantFrom("", "abc", "0x7DC", "-2024"),
        ),
        (s) => {
          expect(parseYearParam(s)).toBeNull();
        },
      ),
    );
    expect(parseYearParam(null)).toBeNull();
    expect(parseYearParam(undefined)).toBeNull();
  });
});

describe("Property 7: Action targets", () => {
  /** **Validates: Requirements 3.2, 3.3, 3.4, 3.5** */
  it("resolves the current property, the only property, a picker or unavailable", () => {
    fc.assert(
      fc.property(
        actionArb,
        propsArb,
        fc.option(idArb, { nil: null }),
        (action, properties, current) => {
          const target = resolveActionTarget(action, properties, current);
          const segment = SEGMENTS[action];
          if (current !== null) {
            expect(target).toEqual({
              kind: "navigate",
              to: `/properties/${current}/${segment}?new=1`,
            });
          } else if (properties.length === 0) {
            expect(target).toEqual({
              kind: "unavailable",
              reason: NO_PROPERTY_REASON,
            });
          } else if (properties.length === 1) {
            expect(target).toEqual({
              kind: "navigate",
              to: `/properties/${properties[0].id}/${segment}?new=1`,
            });
          } else {
            expect(target).toEqual({ kind: "pickProperty" });
          }
        },
      ),
    );
  });
});
