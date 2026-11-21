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

/**
 * Property tests for the carryforward status label, row highlight and cell
 * count (task 6.5). Each run renders the real page with an injected fake API
 * and generated `ReconciledYear` rows.
 */

const STATUS_CELL = 7;

const statusArb = fc.constantFrom<ReconciledYear["status"]>(
  "ok",
  "mismatch",
  "carried",
  "unreported",
);

const carriedFromArb = fc.option(fc.integer({ min: 1990, max: 2100 }), {
  nil: null,
});

/** Signed cents rendered as a two-decimal string, or null. */
const driftArb = fc.option(
  fc.integer({ min: -100_000_000, max: 100_000_000 }).map((cents) => {
    const sign = cents < 0 ? "-" : "";
    const abs = Math.abs(cents);
    return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
  }),
  { nil: null },
);

const netArb = fc.constantFrom("-2500.00", "0.00", "1800.00");

interface RowSpec {
  status: ReconciledYear["status"];
  carriedFrom: number | null;
  drift: string | null;
  net: string;
  reported: boolean;
}

const rowSpecArb: fc.Arbitrary<RowSpec> = fc.record({
  status: statusArb,
  carriedFrom: carriedFromArb,
  drift: driftArb,
  net: netArb,
  reported: fc.boolean(),
});

function buildYears(specs: readonly RowSpec[]): ReconciledYear[] {
  return specs.map((s, i) => ({
    tax_year: 2000 + i,
    schedule_e_net: s.net,
    expected_carry_in: "100.00",
    expected_carryforward: "100.00",
    reported_carryforward: s.reported ? "100.00" : null,
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
    next_year_expected_carry_in: "100.00",
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

async function renderRows(years: ReconciledYear[]) {
  render(
    <MemoryRouter initialEntries={["/carryforward"]}>
      <CarryforwardPage api={makeApi(years)} />
    </MemoryRouter>,
  );
  await screen.findByRole("table");
  const table = screen.getByRole("table");
  const body = table.querySelector("tbody") as HTMLElement;
  return {
    table,
    rows: Array.from(body.querySelectorAll("tr")) as HTMLElement[],
  };
}

function expectedLabel(s: RowSpec): string {
  switch (s.status) {
    case "ok":
      return "OK";
    case "mismatch":
      return "Needs review";
    case "unreported":
      return "Not reported";
    case "carried":
      return s.carriedFrom !== null
        ? `Carried from ${s.carriedFrom}`
        : "Carried from earlier year";
  }
}

describe("CarryforwardPage label, highlight and cell count properties", () => {
  afterEach(() => cleanup());

  // Feature: carryforward-chain-status, Property 11: Status label and highlight depend only on status and root-cause year
  // **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**
  it("labels each status correctly and highlights only mismatch rows", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.array(rowSpecArb, { minLength: 1, maxLength: 6 }),
        async (specs) => {
          const { rows } = await renderRows(buildYears(specs));
          try {
            expect(rows).toHaveLength(specs.length);
            specs.forEach((spec, i) => {
              const row = rows[i];
              const statusCell = row.querySelectorAll("td")[STATUS_CELL];
              // The cell may also hold a hint line; the label is the first span.
              const label = statusCell.querySelector("span") as HTMLElement;
              expect(label.textContent?.trim()).toBe(expectedLabel(spec));
              const isMismatch = spec.status === "mismatch";
              expect(row.className.includes("bg-danger-subtle")).toBe(
                isMismatch,
              );
              expect(label.className.includes("text-danger")).toBe(isMismatch);
            });
          } finally {
            cleanup();
          }
        },
      ),
      { numRuns: 100 },
    );
  }, 30000);

  // Feature: carryforward-chain-status, Property 12: Rows have a constant cell count
  // **Validates: Requirements 7.1, 7.7**
  it("renders every row with the same cell count as the header", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.array(rowSpecArb, { minLength: 1, maxLength: 6 }),
        async (specs) => {
          const { table, rows } = await renderRows(buildYears(specs));
          try {
            const headerCount = within(table).getAllByRole("columnheader")
              .length;
            expect(headerCount).toBe(8);
            expect(rows).toHaveLength(specs.length);
            for (const row of rows) {
              expect(row.querySelectorAll("td")).toHaveLength(headerCount);
            }
          } finally {
            cleanup();
          }
        },
      ),
      { numRuns: 100 },
    );
  }, 30000);
});
