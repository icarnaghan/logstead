import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import * as fc from "fast-check";
import { afterEach, describe, expect, it, vi } from "vitest";
import CarryforwardPage from "./CarryforwardPage";
import type {
  CarryforwardApi,
  ReconciledYear,
  ReconciliationSummary,
} from "../api/carryforward";
import { formatMoneyWholeDollars } from "../lib/money";

/**
 * Property test for the mismatch hint. Each run renders the real page with an
 * injected fake API and generated rows whose carry-out and reported figures
 * come from integer cents.
 */

const STATUS_CELL = 7;

const statusArb = fc.constantFrom<ReconciledYear["status"]>(
  "ok",
  "mismatch",
  "carried",
  "unreported",
);

/** Cents rendered as a two-decimal Money_String. */
function moneyString(cents: number): string {
  const abs = Math.abs(cents);
  return `${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
}

const centsArb = fc.integer({ min: 0, max: 100_000_000 });

interface RowSpec {
  status: ReconciledYear["status"];
  expectedOutCents: number;
  reportedCents: number | null;
}

const rowSpecArb: fc.Arbitrary<RowSpec> = fc.record({
  status: statusArb,
  expectedOutCents: centsArb,
  reportedCents: fc.option(centsArb, { nil: null }),
});

function buildYears(specs: readonly RowSpec[]): ReconciledYear[] {
  return specs.map((s, i) => ({
    tax_year: 2000 + i,
    schedule_e_net: "0.00",
    expected_carry_in: "0.00",
    expected_carryforward: moneyString(s.expectedOutCents),
    reported_carryforward:
      s.reportedCents === null ? null : moneyString(s.reportedCents),
    allowed_loss: "0.00",
    fully_allowed: false,
    status: s.status,
    drift: null,
    carried_from_year: null,
  }));
}

function makeApi(years: ReconciledYear[]): CarryforwardApi {
  const summary: ReconciliationSummary = {
    opening_balance: "0.00",
    status_tolerance: "2.00",
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

describe("CarryforwardPage mismatch hint properties", () => {
  afterEach(() => cleanup());

  // Feature: carryforward-tolerance-and-year-range, Property 9: Mismatch hint content
  // **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6**
  it("shows the hint only on mismatch rows with the previous year and both figures", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.array(rowSpecArb, { minLength: 1, maxLength: 6 }),
        async (specs) => {
          const years = buildYears(specs);
          render(
            <MemoryRouter initialEntries={["/carryforward"]}>
              <CarryforwardPage api={makeApi(years)} />
            </MemoryRouter>,
          );
          try {
            const table = await screen.findByRole("table");
            const body = table.querySelector("tbody") as HTMLElement;
            const rows = Array.from(body.querySelectorAll("tr"));
            expect(rows).toHaveLength(years.length);

            years.forEach((year, i) => {
              const text =
                rows[i].querySelectorAll("td")[STATUS_CELL].textContent ?? "";
              const previous = years[i - 1];

              if (year.status !== "mismatch") {
                expect(text).not.toMatch(
                  /carried out about|Compared with|not reported, so/,
                );
                return;
              }
              if (!previous) {
                expect(text).toContain("Compared with your opening balance.");
                return;
              }
              if (previous.reported_carryforward === null) {
                expect(text).toContain(
                  `The ${previous.tax_year} return is not reported, so this was compared with the expected figure only.`,
                );
                return;
              }
              expect(text).toContain(String(previous.tax_year));
              expect(text).toContain(
                `carried out about ${formatMoneyWholeDollars(previous.expected_carryforward)}`,
              );
              expect(text).toContain(
                `line shows ${formatMoneyWholeDollars(year.reported_carryforward ?? "0.00")}`,
              );
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
