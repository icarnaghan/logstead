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
import { formatMoneyWholeDollars } from "../lib/money";

/**
 * Property test for the carry-in / carry-out columns and the constant cell
 * count. Each run renders the real page with an injected fake API and
 * generated `ReconciledYear` rows.
 */

const ENTERING_CELL = 2;
const CARRY_OUT_CELL = 6;

const statusArb = fc.constantFrom<ReconciledYear["status"]>(
  "ok",
  "mismatch",
  "carried",
  "unreported",
);

/** Cents rendered as a two-decimal Money_String. */
function moneyString(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
}

const nonNegativeMoneyArb = fc
  .integer({ min: 0, max: 100_000_000 })
  .map(moneyString);

const signedMoneyArb = fc
  .integer({ min: -100_000_000, max: 100_000_000 })
  .map(moneyString);

interface RowSpec {
  status: ReconciledYear["status"];
  carriedFrom: number | null;
  drift: string | null;
  net: string;
  expectedIn: string;
  expectedOut: string;
  reported: string | null;
}

const rowSpecArb: fc.Arbitrary<RowSpec> = fc.record({
  status: statusArb,
  carriedFrom: fc.option(fc.integer({ min: 1990, max: 2100 }), { nil: null }),
  drift: fc.option(signedMoneyArb, { nil: null }),
  net: signedMoneyArb,
  expectedIn: nonNegativeMoneyArb,
  expectedOut: nonNegativeMoneyArb,
  reported: fc.option(nonNegativeMoneyArb, { nil: null }),
});

function buildYears(specs: readonly RowSpec[]): ReconciledYear[] {
  return specs.map((s, i) => ({
    tax_year: 2000 + i,
    schedule_e_net: s.net,
    expected_carry_in: s.expectedIn,
    expected_carryforward: s.expectedOut,
    reported_carryforward: s.reported,
    allowed_loss: "0.00",
    fully_allowed: false,
    status: s.status,
    drift: s.drift,
    carried_from_year: s.carriedFrom,
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

describe("CarryforwardPage carry-in / carry-out properties", () => {
  afterEach(() => cleanup());

  // Feature: carryforward-carry-in-semantics, Property 12: Rows show carry-in and carry-out and have a constant cell count
  // **Validates: Requirements 8.1, 8.3, 8.6, 8.7**
  it("shows carry-in and carry-out cells and keeps a constant cell count", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.array(rowSpecArb, { minLength: 1, maxLength: 6 }),
        async (specs) => {
          render(
            <MemoryRouter initialEntries={["/carryforward"]}>
              <CarryforwardPage api={makeApi(buildYears(specs))} />
            </MemoryRouter>,
          );
          try {
            const table = await screen.findByRole("table");
            const headers = within(table).getAllByRole("columnheader");
            const headerText = headers.map((h) => h.textContent?.trim());
            expect(headerText[ENTERING_CELL]).toBe("Expected entering year");
            expect(headerText[CARRY_OUT_CELL]).toBe("Expected to carry out");

            const body = table.querySelector("tbody") as HTMLElement;
            const rows = Array.from(body.querySelectorAll("tr"));
            expect(rows).toHaveLength(specs.length);
            specs.forEach((spec, i) => {
              const cells = rows[i].querySelectorAll("td");
              expect(cells).toHaveLength(headers.length);
              expect(cells[ENTERING_CELL].textContent?.trim()).toBe(
                formatMoneyWholeDollars(spec.expectedIn),
              );
              expect(cells[CARRY_OUT_CELL].textContent?.trim()).toBe(
                formatMoneyWholeDollars(spec.expectedOut),
              );
            });
          } finally {
            cleanup();
          }
        },
      ),
      { numRuns: 100 },
    );
  }, 30000);
});
