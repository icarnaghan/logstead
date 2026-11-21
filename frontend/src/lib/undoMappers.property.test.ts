import { describe, expect, it } from "vitest";
import fc from "fast-check";
import type { DepreciableAsset } from "../api/assets";
import type { Loan } from "../api/loans";
import type { Transaction } from "../api/transactions";
import { assetToInput, loanToInput, transactionToInput } from "./undoMappers";

// Feature: ui-polish-and-consistency, Property 11: Undo mappers reproduce the retained fields
// **Validates: Requirements 13.3**

const NUM_RUNS = 100;

const money = fc
  .tuple(fc.integer({ min: 0, max: 9_999_999 }), fc.integer({ min: 0, max: 99 }))
  .map(([d, c]) => `${d}.${String(c).padStart(2, "0")}`);
const isoDate = fc
  .date({ min: new Date("2000-01-01"), max: new Date("2100-01-01"), noInvalidDate: true })
  .map((d) => d.toISOString().slice(0, 10));
const timestamp = fc
  .date({ noInvalidDate: true })
  .map((d) => d.toISOString());
const text = fc.string({ maxLength: 40 });

const transactionArb: fc.Arbitrary<Transaction> = fc
  .record({
    id: fc.uuid(),
    property_id: fc.uuid(),
    date: isoDate,
    amount: money,
    type: fc.constantFrom("income" as const, "expense" as const),
    category_id: fc.uuid(),
    description: fc.option(text, { nil: undefined }),
    nullDescription: fc.boolean(),
    imported: fc.option(fc.boolean(), { nil: undefined }),
  })
  .map(({ nullDescription, description, imported, ...rest }) => {
    const t: Record<string, unknown> = { ...rest };
    if (description !== undefined) t.description = description;
    else if (nullDescription) t.description = null;
    if (imported !== undefined) t.imported = imported;
    return t as unknown as Transaction;
  });

const assetArb: fc.Arbitrary<DepreciableAsset> = fc
  .record({
    id: fc.uuid(),
    description: text,
    cost_basis: money,
    placed_in_service_date: isoDate,
    recovery_period_years: fc.integer({ min: 1, max: 40 }),
    created_at: timestamp,
    updated_at: timestamp,
    overrides: fc.option(
      fc.dictionary(fc.integer({ min: 2000, max: 2100 }).map(String), money),
      { nil: undefined },
    ),
  })
  .map(({ overrides, ...rest }) => {
    const a: Record<string, unknown> = { ...rest };
    if (overrides !== undefined) a.depreciation_overrides = overrides;
    return a as unknown as DepreciableAsset;
  });

const loanArb: fc.Arbitrary<Loan> = fc
  .record({
    id: fc.uuid(),
    property_id: fc.uuid(),
    description: text,
    annual_interest_rate: fc.double({ min: 0, max: 20, noNaN: true }).map((n) => n.toFixed(4)),
    monthly_payment: money,
    anchor_balance: money,
    anchor_date: isoDate,
    extra_principal: money,
    payoff_date: fc.option(isoDate, { nil: null }),
    original_principal: fc.option(money, { nil: null }),
    closing_date: fc.option(isoDate, { nil: null }),
    include_in_report: fc.boolean(),
    interest_overrides: fc.dictionary(fc.integer({ min: 2000, max: 2100 }).map(String), money),
    remaining_payments: fc.nat(600),
    next_payment_date: isoDate,
    projected_payoff_date: fc.option(isoDate, { nil: null }),
    payoff_balance: fc.option(money, { nil: null }),
    status: fc.constantFrom("active" as const, "ended" as const),
    created_at: timestamp,
    updated_at: timestamp,
  });

const SERVER_ONLY = ["id", "property_id", "created_at", "updated_at", "imported"];

describe("Property 11: Undo mappers reproduce the retained fields", () => {
  it("transactionToInput keeps exactly the create-input keys and values", () => {
    fc.assert(
      fc.property(transactionArb, (t) => {
        const out = transactionToInput(t) as unknown as Record<string, unknown>;
        const expectedKeys = ["date", "amount", "type", "category_id"];
        if (t.description != null) expectedKeys.push("description");
        expect(Object.keys(out).sort()).toEqual(expectedKeys.sort());
        for (const k of expectedKeys) {
          expect(out[k]).toEqual((t as unknown as Record<string, unknown>)[k]);
        }
        for (const k of SERVER_ONLY) expect(k in out).toBe(false);
      }),
      { numRuns: NUM_RUNS },
    );
  });

  it("assetToInput keeps exactly the create-input keys and values", () => {
    fc.assert(
      fc.property(assetArb, (a) => {
        const out = assetToInput(a) as unknown as Record<string, unknown>;
        const expectedKeys = [
          "description",
          "cost_basis",
          "placed_in_service_date",
          "recovery_period_years",
        ];
        if (a.depreciation_overrides !== undefined) expectedKeys.push("depreciation_overrides");
        expect(Object.keys(out).sort()).toEqual(expectedKeys.sort());
        for (const k of expectedKeys) {
          expect(out[k]).toEqual((a as unknown as Record<string, unknown>)[k]);
        }
        for (const k of SERVER_ONLY) expect(k in out).toBe(false);
      }),
      { numRuns: NUM_RUNS },
    );
  });

  it("loanToInput keeps exactly the LoanInput keys and values", () => {
    fc.assert(
      fc.property(loanArb, (l) => {
        const out = loanToInput(l) as unknown as Record<string, unknown>;
        const expectedKeys = [
          "description",
          "annual_interest_rate",
          "monthly_payment",
          "anchor_balance",
          "anchor_date",
          "extra_principal",
          "payoff_date",
          "original_principal",
          "closing_date",
          "include_in_report",
        ];
        expect(Object.keys(out).sort()).toEqual(expectedKeys.sort());
        for (const k of expectedKeys) {
          expect(out[k]).toEqual((l as unknown as Record<string, unknown>)[k]);
        }
        for (const k of [...SERVER_ONLY, "interest_overrides", "status"]) {
          expect(k in out).toBe(false);
        }
      }),
      { numRuns: NUM_RUNS },
    );
  });
});
