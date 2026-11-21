import { describe, expect, it } from "vitest";
import fc from "fast-check";

import type { ReconciledYear } from "../api/carryforward";
import { summarizeChainBreaks } from "./carryforwardChain";

/**
 * Property tests for break amounts and the total gap. The generators and the
 * BigInt-cent oracle are local to this file; the oracle parses and formats
 * money strings itself so it shares no code with the module under test.
 */

type Status = ReconciledYear["status"];

const NUM_RUNS = 200;
const MONEY_SHAPE = /^-?\d+\.\d{2}$/;

// Up to +/- 10^12 cents (about $10 billion): large, but every difference of two
// drifts stays within Number.MAX_SAFE_INTEGER, which the code under test uses.
const MAX_CENTS = 1_000_000_000_000n;
const centsArb: fc.Arbitrary<bigint> = fc.oneof(
  fc.bigInt({ min: -MAX_CENTS, max: MAX_CENTS }),
  fc.bigInt({ min: -100_000n, max: 100_000n }),
);

/** Oracle formatting: BigInt cents to a two-decimal Money_String. */
function fmt(cents: bigint): string {
  const neg = cents < 0n;
  const abs = neg ? -cents : cents;
  const rem = (abs % 100n).toString().padStart(2, "0");
  return `${neg ? "-" : ""}${abs / 100n}.${rem}`;
}

/** Oracle parsing: two-decimal Money_String to BigInt cents. */
function parse(money: string): bigint {
  const neg = money.startsWith("-");
  const [d, c] = (neg ? money.slice(1) : money).split(".");
  const v = BigInt(d) * 100n + BigInt(c);
  return neg ? -v : v;
}

function makeRow(
  index: number,
  status: Status,
  driftCents: bigint | null,
): ReconciledYear {
  return {
    tax_year: 2000 + index,
    schedule_e_net: "0.00",
    expected_carryforward: "0.00",
    reported_carryforward: driftCents === null ? null : "0.00",
    expected_carry_in: "0.00",
    allowed_loss: "0.00",
    fully_allowed: false,
    status,
    drift: driftCents === null ? null : fmt(driftCents),
    carried_from_year: null,
  };
}

/** Free-form series: arbitrary statuses and drifts (mismatch rows always have one). */
const seriesArb: fc.Arbitrary<ReconciledYear[]> = fc
  .array(
    fc.record({
      status: fc.constantFrom<Status>("ok", "mismatch", "carried", "unreported"),
      drift: centsArb,
    }),
    { minLength: 1, maxLength: 12 },
  )
  .map((rows) =>
    rows.map((r, i) =>
      makeRow(i, r.status, r.status === "unreported" ? null : r.drift),
    ),
  );

/**
 * Telescoping series: every non-mismatch reported row repeats the drift of the
 * nearest earlier row with a drift (zero when there is none), so each break's
 * amount is exactly the step from the previous level.
 */
const telescopingArb: fc.Arbitrary<ReconciledYear[]> = fc
  .array(
    fc.record({
      status: fc.constantFrom<Status>("ok", "mismatch", "carried", "unreported"),
      drift: centsArb,
    }),
    { minLength: 1, maxLength: 12 },
  )
  .map((rows) => {
    let level = 0n;
    return rows.map((r, i) => {
      if (r.status === "unreported") return makeRow(i, r.status, null);
      if (r.status === "mismatch") {
        level = r.drift;
        return makeRow(i, r.status, level);
      }
      return makeRow(i, r.status, level);
    });
  });

interface OracleRun {
  start: number;
  end: number;
  startAmount: bigint;
  endAmount: bigint;
}

/** Plain-loop oracle for runs, amounts and the latest non-null drift. */
function oracle(years: readonly ReconciledYear[]): {
  runs: OracleRun[];
  lastDrift: { year: number; drift: bigint } | null;
} {
  const runs: OracleRun[] = [];
  let latest: bigint | null = null;
  let lastDrift: { year: number; drift: bigint } | null = null;
  let current: OracleRun | null = null;
  let currentBaseline = 0n;
  for (const y of years) {
    const d = y.drift === null ? null : parse(y.drift);
    if (y.status === "mismatch") {
      const v = d ?? 0n;
      if (current === null) {
        currentBaseline = latest ?? 0n;
        current = {
          start: y.tax_year,
          end: y.tax_year,
          startAmount: v - currentBaseline,
          endAmount: v - currentBaseline,
        };
        runs.push(current);
      } else {
        current.end = y.tax_year;
        current.endAmount = v - currentBaseline;
      }
    } else {
      current = null;
    }
    if (d !== null) {
      latest = d;
      lastDrift = { year: y.tax_year, drift: d };
    }
  }
  return { runs, lastDrift };
}

describe("carryforwardChain amounts and totals (property tests)", () => {
  // Feature: carryforward-chain-break-summary, Property 3: Break amounts are exact drift differences
  it("Property 3: break amounts are exact drift differences", () => {
    // **Validates: Requirements 2.3, 5.2**
    fc.assert(
      fc.property(seriesArb, (years) => {
        const summary = summarizeChainBreaks(years);
        const expected = oracle(years).runs;
        if (expected.length === 0) {
          expect(summary).toBeNull();
          return;
        }
        expect(summary).not.toBeNull();
        const breaks = [summary!.firstBreak, ...summary!.furtherBreaks];
        expect(breaks).toHaveLength(expected.length);
        breaks.forEach((b, i) => {
          expect(b.startYear).toBe(expected[i].start);
          expect(b.endYear).toBe(expected[i].end);
          expect(b.startAmount).toMatch(MONEY_SHAPE);
          expect(b.endAmount).toMatch(MONEY_SHAPE);
          expect(b.startAmount).toBe(fmt(expected[i].startAmount));
          expect(b.endAmount).toBe(fmt(expected[i].endAmount));
        });
      }),
      { numRuns: NUM_RUNS },
    );
  });

  // Feature: carryforward-chain-break-summary, Property 4: Total gap is the latest non-null drift
  it("Property 4: total gap is the latest non-null drift", () => {
    // **Validates: Requirements 3.4**
    fc.assert(
      fc.property(seriesArb, (years) => {
        const summary = summarizeChainBreaks(years);
        const { runs, lastDrift } = oracle(years);
        fc.pre(runs.length > 0);
        expect(summary).not.toBeNull();
        expect(lastDrift).not.toBeNull();
        expect(summary!.totalGap.year).toBe(lastDrift!.year);
        expect(summary!.totalGap.drift).toMatch(MONEY_SHAPE);
        expect(parse(summary!.totalGap.drift)).toBe(lastDrift!.drift);
      }),
      { numRuns: NUM_RUNS },
    );
  });

  // Feature: carryforward-chain-break-summary, Property 5: Break amounts account for the total gap
  it("Property 5: break amounts account for the total gap", () => {
    // **Validates: Requirements 2.3, 3.1**
    fc.assert(
      fc.property(telescopingArb, (years) => {
        const summary = summarizeChainBreaks(years);
        fc.pre(years.some((y) => y.status === "mismatch"));
        expect(summary).not.toBeNull();
        const breaks = [summary!.firstBreak, ...summary!.furtherBreaks];
        const sum = breaks.reduce((acc, b) => acc + parse(b.endAmount), 0n);
        expect(sum).toBe(parse(summary!.totalGap.drift));
        expect(fmt(sum)).toBe(summary!.totalGap.drift);
      }),
      { numRuns: NUM_RUNS },
    );
  });
});
