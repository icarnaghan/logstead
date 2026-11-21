import fc from "fast-check";
import { describe, expect, it } from "vitest";

import { projectLoan, type LoanProjection, type LoanProjectionInput } from "./amortization";

/**
 * Feature: loan-balance-anchor, Property 22: The preview matches the backend and is never stale
 *
 * **Validates: Requirements 10.4, 10.5, 10.6**
 *
 * The oracle is an independent BigInt implementation of the backend engine
 * (`compute_payment_rows`): it works on structured integers (cents, rate x 10^4,
 * day numbers via `Date.UTC`) rather than on strings, so it shares no parsing or
 * date code with `projectLoan`.
 */

const MAX_CENTS = 99_999_999_999n;
const MAX_RATE = 1_000_000n;

interface Spec {
  balance: bigint; // cents
  rate: bigint; // percent x 10^4
  payment: bigint; // cents
  extra: bigint; // cents
  anchor: { y: number; m: number; d: number };
  payoff: { y: number; m: number; d: number } | null;
}

const pad = (n: number, w: number) => String(n).padStart(w, "0");
const iso = (v: { y: number; m: number; d: number }) => `${pad(v.y, 4)}-${pad(v.m, 2)}-${pad(v.d, 2)}`;
const dim = (y: number, m: number) => new Date(Date.UTC(y, m, 0)).getUTCDate();

function cents(v: bigint): string {
  const s = v.toString().padStart(3, "0");
  return `${s.slice(0, -2)}.${s.slice(-2)}`;
}

function interest(balance: bigint, rate: bigint): bigint {
  const num = balance * rate;
  const den = 12_000_000n;
  const q = num / den;
  return 2n * (num % den) >= den ? q + 1n : q;
}

function oracle(s: Spec): LoanProjection | null {
  if (s.anchor.y < 1900 || s.anchor.y > 9999) return null;
  if (s.payment <= interest(s.balance, s.rate)) return null;
  const date = (k: number) => {
    const total = s.anchor.y * 12 + (s.anchor.m - 1) + k;
    const y = Math.floor(total / 12);
    const m = (total % 12) + 1;
    return { y, m, d: Math.min(s.anchor.d, dim(y, m)) };
  };
  const next = date(1);
  if (next.y > 9999) return null;
  if (s.payoff && iso(s.payoff) < iso(next)) return null;

  const due = s.payment + s.extra;
  let balance = s.balance;
  let total = 0n;
  let count = 0;
  let last = iso(next);
  let lastAmount = 0n;
  for (let k = 1; ; k++) {
    const d = date(k);
    if (d.y > 9999) return null;
    if (s.payoff && iso(d) > iso(s.payoff)) break;
    if (k > 600) return null;
    const i = interest(balance, s.rate);
    count = k;
    last = iso(d);
    total += i;
    if (balance + i <= due) {
      lastAmount = balance + i;
      balance = 0n;
      break;
    }
    lastAmount = due;
    balance -= due - i;
  }
  const paidOff = balance === 0n;
  return {
    remainingPayments: count,
    nextPaymentDate: iso(next),
    projectedPayoffDate: paidOff ? last : null,
    payoffBalance: paidOff ? null : cents(balance),
    finalPayment: paidOff ? cents(lastAmount) : null,
    totalInterest: cents(total),
  };
}

function toInput(s: Spec): LoanProjectionInput {
  return {
    anchorBalance: cents(s.balance),
    annualInterestRate: `${s.rate / 10_000n}.${(s.rate % 10_000n).toString().padStart(4, "0")}`,
    monthlyPayment: cents(s.payment),
    extraPrincipal: cents(s.extra),
    anchorDate: iso(s.anchor),
    payoffDate: s.payoff ? iso(s.payoff) : undefined,
  };
}

const dateArb = fc
  .record({ y: fc.integer({ min: 1895, max: 9999 }), m: fc.integer({ min: 1, max: 12 }), d: fc.integer({ min: 1, max: 31 }) })
  .map(({ y, m, d }) => ({ y, m, d: Math.min(d, dim(y, m)) }));

// Mostly plausible dates, with the year boundaries and leap days over-represented.
const anchorArb = fc.oneof(
  { weight: 6, arbitrary: fc.record({ y: fc.integer({ min: 1990, max: 2060 }), m: fc.integer({ min: 1, max: 12 }), d: fc.integer({ min: 1, max: 31 }) }).map(({ y, m, d }) => ({ y, m, d: Math.min(d, dim(y, m)) })) },
  { weight: 1, arbitrary: dateArb },
  { weight: 1, arbitrary: fc.constantFrom({ y: 2024, m: 1, d: 31 }, { y: 2023, m: 12, d: 31 }, { y: 2024, m: 2, d: 29 }, { y: 9999, m: 12, d: 1 }, { y: 9998, m: 12, d: 31 }, { y: 1900, m: 1, d: 1 }) },
);

const specArb: fc.Arbitrary<Spec> = fc
  .record({
    balance: fc.oneof(fc.bigInt({ min: 1n, max: 100_000_000n }), fc.bigInt({ min: 1n, max: MAX_CENTS })),
    rate: fc.oneof(fc.bigInt({ min: 0n, max: 100_000n }), fc.bigInt({ min: 0n, max: MAX_RATE })),
    paymentFactor: fc.bigInt({ min: 1n, max: 1000n }), // payment as a share (per mille) of balance
    paymentAbs: fc.bigInt({ min: 1n, max: 2_000_000n }),
    useAbs: fc.boolean(),
    extra: fc.oneof(fc.constant(0n), fc.bigInt({ min: 0n, max: 500_000n })),
    anchor: anchorArb,
    payoffMonths: fc.option(fc.integer({ min: 0, max: 700 }), { nil: undefined }),
    payoffDay: fc.integer({ min: 1, max: 31 }),
  })
  .map((r): Spec => {
    const raw = r.useAbs ? r.paymentAbs : (r.balance * r.paymentFactor) / 1000n;
    const payment = raw < 1n ? 1n : raw > MAX_CENTS ? MAX_CENTS : raw;
    let payoff: Spec["payoff"] = null;
    if (r.payoffMonths !== undefined) {
      const total = r.anchor.y * 12 + (r.anchor.m - 1) + r.payoffMonths;
      const y = Math.min(Math.floor(total / 12), 9999);
      const m = y === 9999 && Math.floor(total / 12) > 9999 ? 12 : (total % 12) + 1;
      payoff = { y, m, d: Math.min(r.payoffDay, dim(y, m)) };
    }
    return { balance: r.balance, rate: r.rate, payment, extra: r.extra, anchor: r.anchor, payoff };
  });

describe("Property 22: projectLoan matches the backend oracle", () => {
  it("returns the oracle projection, or null exactly when the oracle rejects", () => {
    fc.assert(
      fc.property(specArb, (s) => {
        expect(projectLoan(toInput(s))).toEqual(oracle(s));
      }),
      { numRuns: 500 },
    );
  });

  it("covers both accepted and rejected schedules", () => {
    const outcomes = fc.sample(specArb, 400).map((s) => oracle(s) !== null);
    expect(outcomes).toContain(true);
    expect(outcomes).toContain(false);
  });

  it("returns null for any input that violates the backend grammar", () => {
    const base: LoanProjectionInput = {
      anchorBalance: "100000.00",
      annualInterestRate: "5",
      monthlyPayment: "1000.00",
      anchorDate: "2025-01-15",
    };
    const bad = fc.oneof(
      fc.constantFrom("", " ", "abc", "-1", "1e3", "1,000", ".5", "5.", "NaN", "1.234", "0x10"),
      fc.string({ maxLength: 8 }).filter((v) => !/^\s*\d+(\.\d{1,2})?\s*$/.test(v)),
    );
    const field = fc.constantFrom("anchorBalance", "monthlyPayment", "extraPrincipal") as fc.Arbitrary<
      "anchorBalance" | "monthlyPayment" | "extraPrincipal"
    >;
    expect(projectLoan(base)).not.toBeNull();
    fc.assert(
      fc.property(field, bad, (f, v) => {
        // A blank extra principal means "unset", which is valid.
        fc.pre(!(f === "extraPrincipal" && v.trim() === ""));
        expect(projectLoan({ ...base, [f]: v })).toBeNull();
      }),
      { numRuns: 200 },
    );
    for (const v of ["2025-02-30", "2025-13-01", "2025-1-1", "20250101", "1899-12-31", "10000-01-01", ""]) {
      expect(projectLoan({ ...base, anchorDate: v })).toBeNull();
    }
    for (const v of ["100.0001", "-1", "abc", "", "1e2", "100.00001"]) {
      expect(projectLoan({ ...base, annualInterestRate: v })).toBeNull();
    }
    expect(projectLoan({ ...base, payoffDate: "2025-02-30" })).toBeNull();
    expect(projectLoan({ ...base, payoffDate: "2025-02-14" })).toBeNull(); // before next payment
  });

  it("is a pure function of the current values: any edit sequence equals a fresh projection", () => {
    fc.assert(
      fc.property(fc.array(specArb, { minLength: 1, maxLength: 6 }), (edits) => {
        let shown: LoanProjection | null = null;
        for (const s of edits) shown = projectLoan(toInput(s)); // each edit recomputes
        const final = edits[edits.length - 1];
        expect(shown).toEqual(projectLoan(toInput(final)));
        expect(shown).toEqual(oracle(final));
        // Idempotent: re-reading the same values never changes the result.
        expect(projectLoan(toInput(final))).toEqual(shown);
      }),
      { numRuns: 100 },
    );
  });
});
