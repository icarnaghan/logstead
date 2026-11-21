import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import fc from "fast-check";
import { afterEach, describe, expect, it, vi } from "vitest";
import CarryforwardPage from "./CarryforwardPage";
import type {
  CarryforwardApi,
  ReconciledYear,
  ReconciliationSummary,
} from "../api/carryforward";
import { formatMoneyWholeDollars } from "../lib/money";

/**
 * Property-based test for the Drift cell text cue (task 6.4).
 *
 * Property 10 (Requirements 7.2, 7.3, 7.4, 7.5, 7.6): for any signed
 * two-decimal drift string the rendered drift cell contains the
 * whole-dollar formatter output; a positive value carries a leading "+" and
 * "over"; a negative value carries a minus sign and "under"; zero carries
 * neither word. A null drift renders an em dash.
 */

// Columns: Year 0, Schedule E net 1, Expected entering 2, Prior years' unallowed
// losses 3, Drift 4, Allowed loss 5, Expected to carry out 6, Status 7.
const DRIFT_CELL = 4;
const TAX_YEAR = 2016;

/** Signed two-decimal drift string from integer cents (includes `0.00`). */
const driftString: fc.Arbitrary<string> = fc
  .integer({ min: -99_999_999_99, max: 99_999_999_99 })
  .map((cents) => {
    const abs = Math.abs(cents);
    const dollars = Math.floor(abs / 100);
    const rest = String(abs % 100).padStart(2, "0");
    return `${cents < 0 ? "-" : ""}${dollars}.${rest}`;
  });

/** Bias toward sub-dollar and zero values alongside the full range. */
const driftInput: fc.Arbitrary<string> = fc.oneof(
  driftString,
  fc.integer({ min: -99, max: 99 }).map((cents) => {
    const abs = Math.abs(cents);
    return `${cents < 0 ? "-" : ""}0.${String(abs).padStart(2, "0")}`;
  }),
);

function makeApi(drift: string | null): CarryforwardApi {
  const row: ReconciledYear = {
    tax_year: TAX_YEAR,
    schedule_e_net: "1000.00",
    expected_carry_in: "0.00",
    expected_carryforward: "0.00",
    reported_carryforward: drift === null ? null : "0.00",
    allowed_loss: "0.00",
    fully_allowed: false,
    status: drift === null ? "unreported" : "mismatch",
    drift,
    carried_from_year: null,
  };
  const summary: ReconciliationSummary = {
    opening_balance: "0.00",
    status_tolerance: "2.00",
    has_data: true,
    next_year: TAX_YEAR + 1,
    next_year_expected_carry_in: "0.00",
    years: [row],
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

async function renderDriftCell(drift: string | null): Promise<string> {
  render(
    <MemoryRouter initialEntries={["/carryforward"]}>
      <CarryforwardPage api={makeApi(drift)} />
    </MemoryRouter>,
  );
  const yearCell = await screen.findByText(String(TAX_YEAR));
  const row = yearCell.closest("tr") as HTMLElement;
  return within(row).getAllByRole("cell")[DRIFT_CELL].textContent ?? "";
}

describe("CarryforwardPage drift cell (Property 10)", () => {
  afterEach(() => cleanup());

  // Feature: carryforward-chain-status, Property 10: Drift cell shows direction in text
  it("shows the formatted value with a textual direction cue", async () => {
    await fc.assert(
      fc.asyncProperty(driftInput, async (drift) => {
        cleanup();
        const text = await renderDriftCell(drift);
        const formatted = formatMoneyWholeDollars(drift);
        const isZero = !/[1-9]/.test(drift);
        const isNegative = drift.startsWith("-") && !isZero;

        expect(text).toContain(formatted);
        if (isZero) {
          expect(text).not.toMatch(/over|under/);
          expect(text).not.toContain("+");
        } else if (isNegative) {
          expect(text).toContain("-");
          expect(text).toMatch(/under/);
          expect(text).not.toMatch(/over/);
        } else {
          expect(text.startsWith("+")).toBe(true);
          expect(text).toMatch(/over/);
          expect(text).not.toMatch(/under/);
        }
      }),
      { numRuns: 100 },
    );
  }, 30_000);

  // Feature: carryforward-chain-status, Property 10: null drift renders an em dash
  it("renders an em dash for null drift", async () => {
    const text = await renderDriftCell(null);
    expect(text).toBe("—");
  });
});
