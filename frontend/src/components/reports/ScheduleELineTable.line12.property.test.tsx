import { cleanup, render, screen, within } from "@testing-library/react";
import fc from "fast-check";
import { afterEach, describe, it } from "vitest";
import { ScheduleELineTable } from "./ScheduleELineTable";
import type { Line12Detail, ReportLine } from "../../api/reports";

/**
 * Feature: mortgage-amortization, Property 32: Line 12 report rendering
 * follows the source.
 *
 * **Validates: Requirements 10.1, 10.2, 10.3, 10.5**
 */

const LINES: ReportLine[] = [
  { line: 3, label: "Rents received", kind: "income", total: "24000.00" },
  {
    line: 12,
    label: "Mortgage interest paid to banks",
    kind: "expense",
    total: "9876.54",
  },
];

/** Integer cents -> two-decimal money string without float arithmetic. */
function centsToMoney(cents: number): string {
  const whole = Math.floor(cents / 100);
  const frac = String(cents % 100).padStart(2, "0");
  return `${whole}.${frac}`;
}

/** Integer cents -> the "$1,234.50" display form. */
function centsToDisplay(cents: number): string {
  const whole = String(Math.floor(cents / 100)).replace(
    /\B(?=(\d{3})+(?!\d))/g,
    ",",
  );
  return `$${whole}.${String(cents % 100).padStart(2, "0")}`;
}

const supersededArb = fc
  .record({
    cents: fc.integer({ min: 0, max: 100_000_000_00 }),
    count: fc.integer({ min: 0, max: 500 }),
  })
  .map(({ cents, count }) => ({ cents, count }));

type Case =
  | { kind: "loan-generated"; cents: number; count: number }
  | { kind: "transaction-entered"; cents: number; count: number }
  | { kind: "missing" }
  | { kind: "null" }
  | { kind: "unrecognized"; source: string; cents: number; count: number };

const caseArb: fc.Arbitrary<Case> = fc.oneof(
  supersededArb.map((s) => ({ kind: "loan-generated" as const, ...s })),
  supersededArb.map((s) => ({ kind: "transaction-entered" as const, ...s })),
  fc.constant({ kind: "missing" as const }),
  fc.constant({ kind: "null" as const }),
  fc
    .tuple(
      fc.string().filter((s) => s !== "loan-generated" && s !== "transaction-entered"),
      supersededArb,
    )
    .map(([source, s]) => ({ kind: "unrecognized" as const, source, ...s })),
);

function toLine12(c: Case): Line12Detail | null | undefined {
  switch (c.kind) {
    case "missing":
      return undefined;
    case "null":
      return null;
    default:
      return {
        source: (c.kind === "unrecognized" ? c.source : c.kind) as Line12Detail["source"],
        superseded_manual_interest: {
          amount: centsToMoney(c.cents),
          count: c.count,
        },
      };
  }
}

afterEach(cleanup);

describe("ScheduleELineTable Line 12 — Property 32", () => {
  it("Line 12 row follows the source", () => {
    fc.assert(
      fc.property(caseArb, (c) => {
        const { unmount } = render(
          <ScheduleELineTable caption="c" lines={LINES} line12={toLine12(c)} />,
        );
        try {
          const row = screen.getByRole("row", { name: /mortgage interest/i });
          const rents = screen.getByRole("row", { name: /rents received/i });

          // Never leaks onto other rows.
          if (
            within(rents).queryByText(/loan-generated|superseded|source unavailable/i)
          ) {
            return false;
          }

          const label = within(row).queryByText("Loan-generated");
          const superseded = within(row).queryByText(/superseded/i);
          const unavailable = within(row).queryByText("Line 12 source unavailable");

          if (c.kind === "loan-generated") {
            if (!label || unavailable) return false;
            const positive = c.count > 0 || c.cents > 0;
            if (!positive) return superseded === null;
            const expected = `Superseded manual interest: ${centsToDisplay(c.cents)} (${c.count} transactions)`;
            return superseded !== null && superseded.textContent === expected;
          }
          if (c.kind === "transaction-entered") {
            return label === null && superseded === null && unavailable === null;
          }
          // missing, null, unrecognized
          return label === null && superseded === null && unavailable !== null;
        } finally {
          unmount();
        }
      }),
      { numRuns: 100 },
    );
    // Renders 100 tables; can exceed the 5s default under full-suite load.
  }, 60_000);

  it("transaction-entered renders identically regardless of superseded data", () => {
    fc.assert(
      fc.property(supersededArb, supersededArb, (a, b) => {
        const html = (s: { cents: number; count: number }) => {
          const { container, unmount } = render(
            <ScheduleELineTable
              caption="c"
              lines={LINES}
              line12={{
                source: "transaction-entered",
                superseded_manual_interest: {
                  amount: centsToMoney(s.cents),
                  count: s.count,
                },
              }}
            />,
          );
          const out = container.innerHTML;
          unmount();
          return out;
        };
        return html(a) === html(b);
      }),
      { numRuns: 50 },
    );
  }, 60_000);
});
