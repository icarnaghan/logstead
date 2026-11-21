import { describe, expect, it } from "vitest";
import { projectLoan, type LoanProjectionInput } from "./amortization";
import vectors from "../data/loan-projection-vectors.json";

interface Vector {
  anchor_balance: string;
  annual_interest_rate: string;
  monthly_payment: string;
  extra_principal: string;
  anchor_date: string;
  payoff_date: string | null;
  remaining_payments: number;
  next_payment_date: string;
  projected_payoff_date: string | null;
  payoff_balance: string | null;
  final_payment: string | null;
  total_interest: string;
}

describe("projectLoan golden vectors", () => {
  const all = vectors as Vector[];
  it("has vectors", () => {
    expect(all.length).toBeGreaterThan(0);
  });
  it.each(all.map((v, i) => [i, v] as const))("matches vector %i", (_i, v) => {
    expect(
      projectLoan({
        anchorBalance: v.anchor_balance,
        annualInterestRate: v.annual_interest_rate,
        monthlyPayment: v.monthly_payment,
        extraPrincipal: v.extra_principal,
        anchorDate: v.anchor_date,
        ...(v.payoff_date ? { payoffDate: v.payoff_date } : {}),
      }),
    ).toEqual({
      remainingPayments: v.remaining_payments,
      nextPaymentDate: v.next_payment_date,
      projectedPayoffDate: v.projected_payoff_date,
      payoffBalance: v.payoff_balance,
      finalPayment: v.final_payment,
      totalInterest: v.total_interest,
    });
  });
});

const base: LoanProjectionInput = {
  anchorBalance: "1000.00",
  annualInterestRate: "12",
  monthlyPayment: "600.00",
  anchorDate: "2025-01-31",
};

describe("projectLoan", () => {
  it("projects a two-row loan with a smaller final sweep payment", () => {
    // Row 1: interest 10.00, balance 410.00. Row 2: 410.00 + 4.10 <= 600 -> sweep.
    expect(projectLoan(base)).toEqual({
      remainingPayments: 2,
      nextPaymentDate: "2025-02-28",
      projectedPayoffDate: "2025-03-31",
      payoffBalance: null,
      finalPayment: "414.10",
      totalInterest: "14.10",
    });
  });

  it("handles rate 0 with a short final payment", () => {
    const p = projectLoan({ ...base, annualInterestRate: "0", anchorBalance: "250.00", monthlyPayment: "100.00" });
    expect(p).toMatchObject({ remainingPayments: 3, finalPayment: "50.00", totalInterest: "0.00" });
  });

  it("treats a balance that equals the payment as a single final row", () => {
    const p = projectLoan({ ...base, annualInterestRate: "0", anchorBalance: "100.00", monthlyPayment: "100.00" });
    expect(p).toMatchObject({ remainingPayments: 1, finalPayment: "100.00" });
  });

  it("rounds interest half-up to the cent", () => {
    // 10.00 at 0.6% -> exactly 0.5 cent of interest rounds up to 0.01.
    const p = projectLoan({
      ...base,
      anchorBalance: "10.00",
      annualInterestRate: "0.6",
      monthlyPayment: "5.00",
      anchorDate: "2025-01-15",
    });
    // Rows: 5.01 left, then 0.01 left, then final 0.01. Only the first row accrues interest.
    expect(p).toMatchObject({ remainingPayments: 3, finalPayment: "0.01", totalInterest: "0.01" });
  });

  it("adds extra principal to each payment", () => {
    const p = projectLoan({ ...base, annualInterestRate: "0", monthlyPayment: "100.00", extraPrincipal: "150.00" });
    expect(p).toMatchObject({ remainingPayments: 4, finalPayment: "250.00" });
  });

  describe("payment dates", () => {
    it("clamps from the anchor day without drift", () => {
      const p = projectLoan({ ...base, annualInterestRate: "0", anchorBalance: "100.00", monthlyPayment: "25.00", anchorDate: "2023-12-31" });
      expect(p).toMatchObject({ nextPaymentDate: "2024-01-31", projectedPayoffDate: "2024-04-30", remainingPayments: 4 });
    });

    it("uses Feb 29 in a leap year and Feb 28 otherwise", () => {
      const leap = projectLoan({ ...base, annualInterestRate: "0", anchorDate: "2024-01-31" });
      const plain = projectLoan({ ...base, annualInterestRate: "0", anchorDate: "2023-01-31" });
      expect(leap?.nextPaymentDate).toBe("2024-02-29");
      expect(plain?.nextPaymentDate).toBe("2023-02-28");
    });

    it("treats 1900 as a non-leap year and 2000 as a leap year", () => {
      expect(projectLoan({ ...base, annualInterestRate: "0", anchorDate: "1900-01-31" })?.nextPaymentDate).toBe("1900-02-28");
      expect(projectLoan({ ...base, annualInterestRate: "0", anchorDate: "2000-01-31" })?.nextPaymentDate).toBe("2000-02-29");
    });

    it("rolls over the year boundary", () => {
      expect(projectLoan({ ...base, anchorDate: "2025-12-15" })?.nextPaymentDate).toBe("2026-01-15");
    });
  });

  describe("payoff date", () => {
    const zero = { ...base, annualInterestRate: "0", anchorBalance: "1000.00", monthlyPayment: "100.00", anchorDate: "2025-01-15" };

    it("stops after the payoff date and reports the remaining balance", () => {
      expect(projectLoan({ ...zero, payoffDate: "2025-03-15" })).toEqual({
        remainingPayments: 2,
        nextPaymentDate: "2025-02-15",
        projectedPayoffDate: null,
        payoffBalance: "800.00",
        finalPayment: null,
        totalInterest: "0.00",
      });
    });

    it("includes a payment dated exactly on the payoff date, including Feb 29", () => {
      const p = projectLoan({ ...zero, anchorBalance: "100.00", monthlyPayment: "50.00", anchorDate: "2024-01-31", payoffDate: "2024-02-29" });
      expect(p).toMatchObject({ remainingPayments: 1, payoffBalance: "50.00" });
    });

    it("reports a normal payoff when the payoff date is after the last row", () => {
      const p = projectLoan({ ...zero, anchorBalance: "200.00", payoffDate: "2030-01-01" });
      expect(p).toMatchObject({ remainingPayments: 2, projectedPayoffDate: "2025-03-15", payoffBalance: null });
    });

    it("treats an empty payoff date as unset", () => {
      expect(projectLoan({ ...zero, payoffDate: "" })?.remainingPayments).toBe(10);
    });

    it("returns null when the payoff date precedes the next payment date", () => {
      expect(projectLoan({ ...zero, payoffDate: "2025-02-14" })).toBeNull();
    });
  });

  describe("returns null", () => {
    it("when the payment does not exceed first-month interest", () => {
      expect(projectLoan({ ...base, monthlyPayment: "10.00" })).toBeNull();
      const tiny = { ...base, anchorBalance: "1.00" }; // first-month interest is 0.01
      expect(projectLoan({ ...tiny, monthlyPayment: "0.01" })).toBeNull();
      expect(projectLoan({ ...tiny, monthlyPayment: "0.02" })).not.toBeNull();
    });

    it("when more than 600 payments are needed", () => {
      const zero = { ...base, annualInterestRate: "0", monthlyPayment: "100.00" };
      expect(projectLoan({ ...zero, anchorBalance: "60000.00" })?.remainingPayments).toBe(600);
      expect(projectLoan({ ...zero, anchorBalance: "60000.01" })).toBeNull();
    });

    it("when a payment date passes year 9999", () => {
      const zero = { ...base, annualInterestRate: "0", anchorBalance: "100.00", monthlyPayment: "50.00" };
      expect(projectLoan({ ...zero, anchorDate: "9999-12-01" })).toBeNull();
      expect(projectLoan({ ...zero, anchorDate: "9999-11-01" })).toBeNull();
      expect(projectLoan({ ...zero, anchorBalance: "50.00", anchorDate: "9999-11-01" })?.projectedPayoffDate).toBe("9999-12-01");
    });

    it.each<[string, Partial<LoanProjectionInput>]>([
      ["empty balance", { anchorBalance: "" }],
      ["zero balance", { anchorBalance: "0.00" }],
      ["balance over the maximum", { anchorBalance: "1000000000.00" }],
      ["balance with 3 decimals", { anchorBalance: "10.001" }],
      ["negative payment", { monthlyPayment: "-5" }],
      ["zero payment", { monthlyPayment: "0" }],
      ["non-numeric payment", { monthlyPayment: "12x" }],
      ["rate over 100", { annualInterestRate: "100.0001" }],
      ["rate with 5 decimals", { annualInterestRate: "5.12345" }],
      ["empty rate", { annualInterestRate: "" }],
      ["extra with 3 decimals", { extraPrincipal: "1.001" }],
      ["extra negative", { extraPrincipal: "-1" }],
      ["malformed anchor date", { anchorDate: "2025-1-5" }],
      ["impossible anchor date", { anchorDate: "2025-02-30" }],
      ["anchor before 1900", { anchorDate: "1899-12-31" }],
      ["invalid payoff date", { payoffDate: "2025-13-01" }],
    ])("for %s", (_name, override) => {
      expect(projectLoan({ ...base, ...override })).toBeNull();
    });

    it("accepts boundary values", () => {
      expect(projectLoan({ ...base, annualInterestRate: "100", monthlyPayment: "999999999.99", anchorBalance: "999999999.99" })).not.toBeNull();
      expect(projectLoan({ ...base, anchorDate: "1900-01-01" })).not.toBeNull();
    });
  });
});
