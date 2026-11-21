import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import * as fc from "fast-check";
import { afterEach, describe, expect, it, vi } from "vitest";
import CarryforwardPage from "./CarryforwardPage";
import type {
  CarryforwardApi,
  ReconciledYear,
  ReconciliationSummary,
} from "../api/carryforward";
import {
  carriedBreakInfo,
  summarizeChainBreaks,
  type ChainBreak,
} from "../lib/carryforwardChain";
import { centsToMoney, formatMoneyWholeDollars, toCents } from "../lib/money";

/**
 * Property tests for the chain summary block and the carried-row hint. Each run
 * renders the real page with an injected fake API and a generated series whose
 * amounts come from integer cents.
 */

const STATUS_CELL = 7;
const REGION_NAME = "Where the chain breaks";

const statusArb = fc.constantFrom<ReconciledYear["status"]>(
  "ok",
  "mismatch",
  "carried",
  "unreported",
);

const amountCentsArb = fc.integer({ min: 0, max: 5_000_000 });
const driftCentsArb = fc.integer({ min: -5_000_000, max: 5_000_000 });
const toleranceCentsArb = fc.integer({ min: 0, max: 1000 });

interface RowSpec {
  status: ReconciledYear["status"];
  carryIn: number;
  carryOut: number;
  reported: number;
  drift: number;
}

const rowSpecArb: fc.Arbitrary<RowSpec> = fc.record({
  status: statusArb,
  carryIn: amountCentsArb,
  carryOut: amountCentsArb,
  reported: amountCentsArb,
  drift: driftCentsArb,
});

/** Build a consecutive-year series; `carried` rows point at the latest earlier mismatch. */
function buildYears(specs: readonly RowSpec[]): ReconciledYear[] {
  let lastMismatch: number | null = null;
  return specs.map((s, i) => {
    const taxYear = 2000 + i;
    const reported = s.status !== "unreported";
    const row: ReconciledYear = {
      tax_year: taxYear,
      schedule_e_net: "0.00",
      expected_carry_in: centsToMoney(s.carryIn),
      expected_carryforward: centsToMoney(s.carryOut),
      reported_carryforward: reported ? centsToMoney(s.reported) : null,
      allowed_loss: "0.00",
      fully_allowed: false,
      status: s.status,
      drift: reported ? centsToMoney(s.drift) : null,
      carried_from_year: s.status === "carried" ? lastMismatch : null,
    };
    if (s.status === "mismatch") lastMismatch = taxYear;
    return row;
  });
}

function makeApi(years: ReconciledYear[], tolerance: string): CarryforwardApi {
  const summary: ReconciliationSummary = {
    opening_balance: "0.00",
    status_tolerance: tolerance,
    has_data: true,
    next_year: 2000 + years.length,
    next_year_expected_carry_in: "0.00",
    years,
  };
  return {
    getReconciliation: vi.fn().mockResolvedValue(summary),
    setReported: vi.fn(),
    clearReported: vi.fn(),
    setOpeningBalance: vi.fn(),
    setYear: vi.fn(),
    setAllowedLoss: vi.fn(),
    clearAllowedLoss: vi.fn(),
    setFullyAllowed: vi.fn(),
  } as unknown as CarryforwardApi;
}

function absDollars(amount: string): string {
  return formatMoneyWholeDollars(centsToMoney(Math.abs(toCents(amount))));
}

function renderPage(years: ReconciledYear[], tolerance: string): void {
  render(
    <MemoryRouter initialEntries={["/carryforward"]}>
      <CarryforwardPage api={makeApi(years, tolerance)} />
    </MemoryRouter>,
  );
}

function expectedFirstSentence(b: ChainBreak): string {
  if (b.priorYear !== null && b.priorCarryOut !== null) {
    return `The chain first breaks in ${b.startYear}: the ${b.priorYear} return carried out about ${formatMoneyWholeDollars(b.priorCarryOut)}, but the ${b.startYear} line shows ${formatMoneyWholeDollars(b.reported)}.`;
  }
  return `The chain first breaks in ${b.startYear}: the ${b.startYear} line shows ${formatMoneyWholeDollars(b.reported)}, where about ${formatMoneyWholeDollars(b.expectedCarryIn)} was expected.`;
}

describe("CarryforwardPage chain summary properties", () => {
  afterEach(() => cleanup());

  // Feature: carryforward-chain-break-summary, Property 8: The summary block states the derived facts
  // **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 3.1, 3.2, 3.3**
  it("states the first break, further breaks and total gap, and renders nothing without a mismatch", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.array(rowSpecArb, { minLength: 1, maxLength: 12 }),
        toleranceCentsArb,
        async (specs, tolCents) => {
          const years = buildYears(specs);
          const tolerance = centsToMoney(tolCents);
          const chain = summarizeChainBreaks(years);
          renderPage(years, tolerance);
          try {
            await screen.findByRole("table");

            if (chain === null) {
              expect(
                screen.queryByRole("region", { name: REGION_NAME }),
              ).toBeNull();
              return;
            }

            const region = screen.getByRole("region", { name: REGION_NAME });
            const text = region.textContent ?? "";
            const first = chain.firstBreak;

            expect(text).toContain(expectedFirstSentence(first));

            if (first.endYear > first.startYear) {
              const cents = toCents(first.endAmount);
              const expected =
                cents === 0
                  ? `The mismatch continues through ${first.endYear}, with no net change in total.`
                  : `The mismatch continues through ${first.endYear}, where about ${absDollars(first.endAmount)} appears ${cents < 0 ? "dropped" : "extra"} in total.`;
              expect(text).toContain(expected);
            } else {
              expect(text).not.toContain("The mismatch continues through");
            }

            const items = within(region).queryAllByRole("listitem");
            expect(items).toHaveLength(chain.furtherBreaks.length);
            chain.furtherBreaks.forEach((b, i) => {
              const yearsText =
                b.endYear > b.startYear
                  ? `${b.startYear} to ${b.endYear}`
                  : `${b.startYear}`;
              const cents = toCents(b.endAmount);
              const itemText = items[i].textContent ?? "";
              expect(itemText.startsWith(`${yearsText}:`)).toBe(true);
              if (cents === 0) {
                expect(itemText).toContain("no net change");
              } else {
                expect(itemText).toContain(
                  `about ${absDollars(b.endAmount)} ${cents < 0 ? "dropped" : "extra"}`,
                );
              }
            });

            const gap = chain.totalGap;
            const gapCents = toCents(gap.drift);
            if (Math.abs(gapCents) <= tolCents) {
              expect(text).toContain(
                `As of ${gap.year}, the reported line is within ${formatMoneyWholeDollars(tolerance)} of the expected carry-in.`,
              );
            } else {
              expect(text).toContain(
                `As of ${gap.year}, the reported line is about ${absDollars(gap.drift)} ${gapCents < 0 ? "under" : "over"} the expected carry-in.`,
              );
            }
          } finally {
            cleanup();
          }
        },
      ),
      { numRuns: 100 },
    );
  }, 60000);

  // Feature: carryforward-chain-break-summary, Property 9: Carried rows show the inherited-break hint
  // **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**
  it("shows the inherited-break hint only on carried rows with a break year and drift", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.array(rowSpecArb, { minLength: 1, maxLength: 12 }),
        toleranceCentsArb,
        async (specs, tolCents) => {
          const years = buildYears(specs);
          const chain = summarizeChainBreaks(years);
          renderPage(years, centsToMoney(tolCents));
          try {
            const table = await screen.findByRole("table");
            const body = table.querySelector("tbody") as HTMLElement;
            const rows = Array.from(body.querySelectorAll("tr"));
            expect(rows).toHaveLength(years.length);

            years.forEach((year, i) => {
              const text =
                rows[i].querySelectorAll("td")[STATUS_CELL].textContent ?? "";
              const info = carriedBreakInfo(year, chain);

              if (
                year.status !== "carried" ||
                year.carried_from_year === null ||
                year.drift === null
              ) {
                expect(info).toBeNull();
                expect(text).not.toContain("Inherits the");
                return;
              }

              expect(text).toContain(`Carried from ${year.carried_from_year}`);
              const cents = toCents(year.drift);
              expect(text).toContain(
                `Inherits the ${year.carried_from_year} break: this line is about ${absDollars(year.drift)} ${cents < 0 ? "under" : "over"} the expected carry-in.`,
              );
              const firstYear = chain?.firstBreak.startYear ?? null;
              if (firstYear !== null && firstYear !== year.carried_from_year) {
                expect(text).toContain(
                  `The chain first broke in ${firstYear}.`,
                );
              } else {
                expect(text).not.toContain("The chain first broke in");
              }
            });
          } finally {
            cleanup();
          }
        },
      ),
      { numRuns: 100 },
    );
  }, 60000);
});
