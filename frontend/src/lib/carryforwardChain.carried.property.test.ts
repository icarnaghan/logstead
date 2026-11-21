import fc from "fast-check";
import { describe, expect, it } from "vitest";

import type { ReconciledYear } from "../api/carryforward";
import { carriedBreakInfo, summarizeChainBreaks } from "./carryforwardChain";
import { centsToMoney } from "./money";

const STATUSES = ["ok", "mismatch", "carried", "unreported"] as const;

const centsArb = fc.integer({ min: -5_000_000, max: 5_000_000 });
const nonNegCentsArb = fc.integer({ min: 0, max: 5_000_000 });

/**
 * Local generator: 1 to 12 ascending years with random statuses and
 * integer-cent money. `carried_from_year` and `drift` are sometimes null on
 * carried rows so the null branches of `carriedBreakInfo` are exercised.
 */
const seriesArb: fc.Arbitrary<ReconciledYear[]> = fc
  .record({
    startYear: fc.integer({ min: 2000, max: 2030 }),
    rows: fc.array(
      fc.record({
        status: fc.constantFrom(...STATUSES),
        expectedIn: nonNegCentsArb,
        expectedOut: nonNegCentsArb,
        reported: nonNegCentsArb,
        drift: centsArb,
        driftNull: fc.boolean(),
        fromYearOffset: fc.option(fc.integer({ min: 0, max: 11 }), {
          nil: null,
        }),
      }),
      { minLength: 1, maxLength: 12 },
    ),
  })
  .map(({ startYear, rows }) =>
    rows.map((r, i): ReconciledYear => {
      const unreported = r.status === "unreported";
      const driftNull = unreported || (r.status === "carried" && r.driftNull);
      return {
        tax_year: startYear + i,
        schedule_e_net: "0.00",
        expected_carryforward: centsToMoney(r.expectedOut),
        reported_carryforward: unreported ? null : centsToMoney(r.reported),
        expected_carry_in: centsToMoney(r.expectedIn),
        allowed_loss: "0.00",
        fully_allowed: false,
        status: r.status,
        drift: driftNull ? null : centsToMoney(r.drift),
        carried_from_year:
          r.status === "carried" && r.fromYearOffset !== null
            ? startYear + Math.min(r.fromYearOffset, i)
            : null,
      };
    }),
  );

describe("carryforwardChain carried info and purity (properties)", () => {
  // Feature: carryforward-chain-break-summary, Property 6: Carried-row info reflects the row and the first break
  // **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
  it("carriedBreakInfo reflects the row and the first break", () => {
    fc.assert(
      fc.property(seriesArb, (series) => {
        const summary = summarizeChainBreaks(series);
        const firstMismatch = series.find((y) => y.status === "mismatch");

        for (const row of series) {
          const info = carriedBreakInfo(row, summary);
          const eligible =
            row.status === "carried" &&
            row.carried_from_year !== null &&
            row.drift !== null;

          if (!eligible) {
            expect(info).toBeNull();
            continue;
          }
          const breakYear = row.carried_from_year as number;
          const firstYear = firstMismatch?.tax_year ?? null;
          expect(info).toEqual({
            breakYear,
            drift: row.drift,
            firstBreakYear:
              firstYear !== null && firstYear !== breakYear ? firstYear : null,
          });
        }
      }),
      { numRuns: 100 },
    );
  });

  // Feature: carryforward-chain-break-summary, Property 7: The derivation does not modify its input
  // **Validates: Requirements 5.3**
  it("does not modify its input and repeated calls are equal", () => {
    fc.assert(
      fc.property(seriesArb, (series) => {
        const copy = structuredClone(series);

        const first = summarizeChainBreaks(series);
        const second = summarizeChainBreaks(series);
        const firstInfos = series.map((r) => carriedBreakInfo(r, first));
        const secondInfos = series.map((r) => carriedBreakInfo(r, second));

        expect(series).toEqual(copy);
        expect(second).toEqual(first);
        expect(secondInfos).toEqual(firstInfos);
      }),
      { numRuns: 100 },
    );
  });
});
