import fc from "fast-check";
import { describe, expect, it } from "vitest";

import type { ReconciledYear } from "../api/carryforward";
import { summarizeChainBreaks } from "./carryforwardChain";

/** Integer cents -> two-decimal Money_String (local, independent of lib/money). */
function money(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  const whole = Math.floor(abs / 100);
  const frac = String(abs % 100).padStart(2, "0");
  return `${sign}${whole}.${frac}`;
}

type Status = ReconciledYear["status"];

const centsArb = fc.integer({ min: -1_000_000, max: 1_000_000 });
const nonNegCentsArb = fc.integer({ min: 0, max: 1_000_000 });

/**
 * Ascending series of 1-12 years with random statuses. Carried rows point at
 * the most recent earlier mismatch year (or null); unreported rows have null
 * reported/drift.
 */
const seriesArb: fc.Arbitrary<ReconciledYear[]> = fc
  .record({
    startYear: fc.integer({ min: 2000, max: 2030 }),
    rows: fc.array(
      fc.record({
        status: fc.constantFrom<Status>("ok", "mismatch", "carried", "unreported"),
        carryIn: nonNegCentsArb,
        carryOut: nonNegCentsArb,
        reported: nonNegCentsArb,
        drift: centsArb,
      }),
      { minLength: 1, maxLength: 12 },
    ),
  })
  .map(({ startYear, rows }) => {
    let lastMismatch: number | null = null;
    return rows.map((r, i): ReconciledYear => {
      const year = startYear + i;
      const unreported = r.status === "unreported";
      const row: ReconciledYear = {
        tax_year: year,
        schedule_e_net: "0.00",
        expected_carryforward: money(r.carryOut),
        reported_carryforward: unreported ? null : money(r.reported),
        expected_carry_in: money(r.carryIn),
        allowed_loss: "0.00",
        fully_allowed: false,
        status: r.status,
        drift: unreported ? null : money(r.drift),
        carried_from_year: r.status === "carried" ? lastMismatch : null,
      };
      if (r.status === "mismatch") lastMismatch = year;
      return row;
    });
  });

/** Independent oracle: maximal runs of consecutive mismatch rows, plain loops. */
function oracleRuns(years: readonly ReconciledYear[]): Array<[number, number]> {
  const runs: Array<[number, number]> = [];
  let i = 0;
  while (i < years.length) {
    if (years[i].status === "mismatch") {
      let j = i;
      while (j + 1 < years.length && years[j + 1].status === "mismatch") j++;
      runs.push([years[i].tax_year, years[j].tax_year]);
      i = j + 1;
    } else {
      i++;
    }
  }
  return runs;
}

describe("carryforwardChain break detection properties", () => {
  // Feature: carryforward-chain-break-summary, Property 1: A summary exists exactly when a mismatch row exists
  it("Property 1: summary exists exactly when a mismatch row exists", () => {
    // **Validates: Requirements 1.1, 1.2**
    fc.assert(
      fc.property(seriesArb, (years) => {
        const summary = summarizeChainBreaks(years);
        let firstMismatch: number | null = null;
        for (const y of years) {
          if (y.status === "mismatch") {
            firstMismatch = y.tax_year;
            break;
          }
        }
        if (firstMismatch === null) {
          expect(summary).toBeNull();
        } else {
          expect(summary).not.toBeNull();
          expect(summary!.firstBreak.startYear).toBe(firstMismatch);
        }
      }),
      { numRuns: 200 },
    );
  });

  // Feature: carryforward-chain-break-summary, Property 2: Breaks are the maximal runs of consecutive mismatch rows
  it("Property 2: breaks are the maximal runs of consecutive mismatch rows", () => {
    // **Validates: Requirements 1.5, 2.1, 2.2, 2.4**
    fc.assert(
      fc.property(seriesArb, (years) => {
        const expected = oracleRuns(years);
        const summary = summarizeChainBreaks(years);
        if (expected.length === 0) {
          expect(summary).toBeNull();
          return;
        }
        expect(summary).not.toBeNull();
        const actual = [summary!.firstBreak, ...summary!.furtherBreaks].map(
          (b) => [b.startYear, b.endYear] as [number, number],
        );
        expect(actual).toEqual(expected);
        expect(summary!.furtherBreaks.length).toBe(expected.length - 1);

        // Ascending, non-overlapping, and bounded by non-mismatch rows.
        for (let k = 0; k < actual.length; k++) {
          const [s, e] = actual[k];
          expect(s).toBeLessThanOrEqual(e);
          if (k > 0) expect(s).toBeGreaterThan(actual[k - 1][1]);
          for (const y of years) {
            if (y.tax_year >= s && y.tax_year <= e) {
              expect(y.status).toBe("mismatch");
            }
            if (y.tax_year === s - 1 || y.tax_year === e + 1) {
              expect(y.status).not.toBe("mismatch");
            }
          }
        }
      }),
      { numRuns: 200 },
    );
  });
});
