import { cleanup, render, screen } from "@testing-library/react";
import fc from "fast-check";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ItemizedSummary } from "../../api/itemized";
import { centsToMoney } from "../../lib/money";
import { ItemizedSummaryPanel } from "./ItemizedSummaryPanel";
import { SyncTotalDialog } from "./SyncTotalDialog";

// Feature: itemized-expenses, Property 17: The page's displayed amounts match the integer-cents oracle
// **Validates: Requirements 7.2, 7.3, 9.1, 9.2, 9.3, 14.2**

/** Independent oracle formatter: integer cents to "-$1,234.56" without Intl. */
function oracleMoney(cents: number): string {
  const abs = Math.abs(cents);
  const dollars = String(Math.floor(abs / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${cents < 0 ? "-" : ""}$${dollars}.${String(abs % 100).padStart(2, "0")}`;
}

const entries = fc.array(fc.integer({ min: 1, max: 10_000_000_00 }), {
  minLength: 1,
  maxLength: 30,
});
const total = fc.integer({ min: 1, max: 100_000_000_00 });

describe("Property 17: rendered amounts match the integer-cents oracle", () => {
  afterEach(cleanup);

  it("ItemizedSummaryPanel shows oracle itemized sum and remainder", () => {
    fc.assert(
      fc.property(entries, fc.option(total, { nil: null }), (list, tot) => {
        const sum = list.reduce((a, b) => a + b, 0);
        const summary = {
          category_id: "c",
          label: "Repairs",
          schedule_e_line: 14,
          tax_year: 2024,
          entered_total: tot === null ? null : centsToMoney(tot),
          entered_total_rows: [],
          itemized_sum: centsToMoney(sum),
          itemized_count: list.length,
          entries: [],
          remainder: tot === null ? null : centsToMoney(tot - sum),
          line_total: centsToMoney(tot ?? sum),
          line_source: tot === null ? "itemized" : "entered_total",
          total_differs_from_itemized: tot !== null && tot !== sum,
        } as ItemizedSummary;
        const { unmount } = render(
          <ItemizedSummaryPanel summary={summary} line={14} />,
        );
        try {
          const sumTerm = screen.getByText("Itemized sum");
          expect(sumTerm.nextElementSibling?.textContent).toContain(
            oracleMoney(sum),
          );
          const rem = screen.queryByText("Unitemized remainder");
          if (tot === null) {
            expect(rem).toBeNull();
          } else {
            expect(rem?.nextElementSibling?.textContent).toContain(
              oracleMoney(tot - sum),
            );
          }
        } finally {
          unmount();
        }
      }),
      { numRuns: 100 },
    );
  });

  it("SyncTotalDialog shows oracle old amount, new amount, and signed difference", () => {
    fc.assert(
      fc.property(
        entries,
        total,
        fc.constantFrom(2020, 2024),
        (list, tot, year) => {
          const sum = list.reduce((a, b) => a + b, 0);
          fc.pre(sum !== tot);
          const delta = sum - tot;
          const { unmount } = render(
            <SyncTotalDialog
              open
              onOpenChange={vi.fn()}
              onConfirm={vi.fn()}
              label="Repairs"
              line={14}
              taxYear={year}
              enteredTotal={centsToMoney(tot)}
              itemizedSum={centsToMoney(sum)}
              itemizedCount={list.length}
              currentYear={2024}
            />,
          );
          try {
            expect(screen.getByText(/will change from/).textContent).toContain(
              `from ${oracleMoney(tot)} to ${oracleMoney(sum)} (${delta > 0 ? "+" : ""}${oracleMoney(delta)})`,
            );
          } finally {
            unmount();
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
