import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import {
  isItemizedEntrySafeDelete,
  isLoanSafeDelete,
  isTransactionSafeDelete,
} from "./undoMappers";
import type { Loan } from "../api/loans";
import type { Transaction } from "../api/transactions";

// Feature: ui-polish-and-consistency, Property 10: Safe_Delete classification
describe("Property 10: Safe_Delete classification", () => {
  it("**Validates: Requirements 13.1, 13.7** transaction is safe iff not imported and zero receipts", () => {
    fc.assert(
      fc.property(
        fc.option(fc.boolean(), { nil: undefined }),
        fc.option(fc.nat({ max: 50 }), { nil: null }),
        (imported, count) => {
          const t = { id: 1, imported } as unknown as Transaction;
          expect(isTransactionSafeDelete(t, count)).toBe(
            imported !== true && count === 0,
          );
        },
      ),
      { numRuns: 100 },
    );
  });

  it("**Validates: Requirements 13.1, 13.7** loan is safe iff it has no interest override keys", () => {
    fc.assert(
      fc.property(
        fc.dictionary(fc.string({ minLength: 1, maxLength: 6 }), fc.double({ noNaN: true })),
        (overrides) => {
          const l = { id: 1, interest_overrides: overrides } as unknown as Loan;
          expect(isLoanSafeDelete(l)).toBe(Object.keys(overrides).length === 0);
        },
      ),
      { numRuns: 100 },
    );
  });
});

// Feature: itemized-expenses, Property 18: Undo safety classification for itemized entries and totals
describe("Property 18: Undo safety classification for itemized entries and totals", () => {
  const countArb = fc.option(fc.nat({ max: 50 }), { nil: null });

  it("**Validates: Requirements 10.7, 15.2** itemized totals are never safe to delete", () => {
    fc.assert(
      fc.property(
        fc.option(fc.boolean(), { nil: undefined }),
        countArb,
        (imported, count) => {
          const t = { id: 1, itemized: true, imported } as unknown as Transaction;
          expect(isTransactionSafeDelete(t, count)).toBe(false);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("**Validates: Requirements 10.7, 15.2** itemized entry is safe iff the receipt count is a known zero", () => {
    fc.assert(
      fc.property(countArb, (count) => {
        const e = { id: 2, parent_transaction_id: 1 } as unknown as Transaction;
        expect(isItemizedEntrySafeDelete(e, count)).toBe(count === 0);
      }),
      { numRuns: 100 },
    );
  });
});
