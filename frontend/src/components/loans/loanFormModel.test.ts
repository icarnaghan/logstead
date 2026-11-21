import { describe, expect, it } from "vitest";
import {
  EMPTY_LOAN_FORM,
  LOAN_FIELD_BY_API_NAME,
  emptyLoanForm,
  todayIso,
  toLoanInput,
  validateLoanForm,
  type LoanFormValues,
} from "./loanFormModel";

const valid: LoanFormValues = {
  ...emptyLoanForm("2024-01-15"),
  description: "Main mortgage",
  annualInterestRate: "6.8750",
  monthlyPayment: "1500.00",
  anchorBalance: "200000.00",
  anchorDate: "2024-01-15",
};

const errorsFor = (patch: Partial<LoanFormValues>) =>
  validateLoanForm({ ...valid, ...patch });

describe("todayIso / emptyLoanForm", () => {
  it("formats the injected clock as a local ISO date (10.2)", () => {
    expect(todayIso(new Date(2025, 5, 2, 23, 59))).toBe("2025-06-02");
    expect(todayIso(new Date(2025, 0, 9))).toBe("2025-01-09");
  });

  it("defaults the anchor date to the injected day (10.2)", () => {
    const form = emptyLoanForm("2030-03-04");
    expect(form.anchorDate).toBe("2030-03-04");
    expect(form.includeInReport).toBe(true);
    expect(EMPTY_LOAN_FORM.anchorDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe("LOAN_FIELD_BY_API_NAME", () => {
  it("maps anchor-shape API names and drops origination names", () => {
    expect(LOAN_FIELD_BY_API_NAME.monthly_payment).toBe("monthlyPayment");
    expect(LOAN_FIELD_BY_API_NAME.anchor_balance).toBe("anchorBalance");
    expect(LOAN_FIELD_BY_API_NAME.anchor_date).toBe("anchorDate");
    expect(LOAN_FIELD_BY_API_NAME.term_months).toBeUndefined();
    expect(LOAN_FIELD_BY_API_NAME.first_payment_date).toBeUndefined();
  });
});

describe("validateLoanForm", () => {
  it("accepts a valid form", () => {
    expect(validateLoanForm(valid)).toEqual({});
  });

  it("requires every required field (1.2)", () => {
    const errors = validateLoanForm(emptyLoanForm("2024-01-15"));
    expect(Object.keys(errors).sort()).toEqual(
      ["anchorBalance", "annualInterestRate", "description", "monthlyPayment"].sort(),
    );
  });

  it("validates description length 1..200", () => {
    expect(errorsFor({ description: "   " }).description).toBeDefined();
    expect(errorsFor({ description: "a".repeat(200) }).description).toBeUndefined();
    expect(errorsFor({ description: "a".repeat(201) }).description).toBeDefined();
  });

  it.each(["0", "0.00", "-1", "1000000000.00", "100.123", "abc", ""])(
    "rejects anchor balance %s (1.4)",
    (anchorBalance) => {
      expect(errorsFor({ anchorBalance }).anchorBalance).toBeDefined();
    },
  );

  it.each(["0.01", "100"])("accepts anchor balance %s (1.4)", (anchorBalance) => {
    expect(
      errorsFor({ anchorBalance, monthlyPayment: "1000.00", annualInterestRate: "0" })
        .anchorBalance,
    ).toBeUndefined();
  });

  it.each(["0", "0.00", "-1", "1000000000.00", "10.123", "abc", ""])(
    "rejects monthly payment %s (1.5)",
    (monthlyPayment) => {
      expect(errorsFor({ monthlyPayment }).monthlyPayment).toBeDefined();
    },
  );

  it.each(["-0.1", "100.0001", "1.12345", "x", ""])("rejects rate %s (1.6)", (annualInterestRate) => {
    expect(errorsFor({ annualInterestRate }).annualInterestRate).toBeDefined();
  });

  it.each(["0", "100", "100.0000", "0.0001"])("accepts rate %s (1.6)", (annualInterestRate) => {
    expect(
      errorsFor({ annualInterestRate, monthlyPayment: "300000.00" }).annualInterestRate,
    ).toBeUndefined();
  });

  it.each(["2024-02-30", "2024-13-01", "02/01/2024", "2024-2-1", "", "1899-12-31"])(
    "rejects anchor date %s (1.7)",
    (anchorDate) => {
      expect(errorsFor({ anchorDate }).anchorDate).toBeDefined();
    },
  );

  it("accepts a leap day and rejects a non-leap one (1.7)", () => {
    expect(errorsFor({ anchorDate: "2024-02-29" }).anchorDate).toBeUndefined();
    expect(errorsFor({ anchorDate: "2023-02-29" }).anchorDate).toBeDefined();
  });

  it("requires the payment to exceed first-month interest (1.8)", () => {
    // 200000 * 6.875% / 12 = 1145.83; payoff date keeps the 600-row cap out of play.
    const base = { payoffDate: "2025-01-15" };
    expect(errorsFor({ ...base, monthlyPayment: "1145.83" }).monthlyPayment).toMatch(
      /exceed the first month/,
    );
    expect(errorsFor({ ...base, monthlyPayment: "1145.84" }).monthlyPayment).toBeUndefined();
  });

  it("rejects a schedule needing more than 600 payments (2.14)", () => {
    const errors = errorsFor({ monthlyPayment: "1146.00" });
    expect(errors.monthlyPayment).toMatch(/more than 600/);
    expect(errors.anchorDate).toBeUndefined();
  });

  it("accepts a schedule of exactly 600 payments (2.14)", () => {
    // Zero rate, 600 payments of 100.00.
    expect(
      errorsFor({ annualInterestRate: "0", anchorBalance: "60000.00", monthlyPayment: "100.00" }),
    ).toEqual({});
    expect(
      errorsFor({ annualInterestRate: "0", anchorBalance: "60000.01", monthlyPayment: "100.00" })
        .monthlyPayment,
    ).toMatch(/more than 600/);
  });

  it("rejects a schedule running past year 9999 (2.15)", () => {
    const errors = errorsFor({
      annualInterestRate: "0",
      anchorDate: "9999-06-15",
      anchorBalance: "1000.00",
      monthlyPayment: "100.00",
    });
    expect(errors.anchorDate).toMatch(/9999/);
    expect(errors.monthlyPayment).toBeUndefined();
  });

  it("validates extra principal (0 allowed, negative or >2dp rejected) (3.2)", () => {
    expect(errorsFor({ extraPrincipal: "0" }).extraPrincipal).toBeUndefined();
    expect(errorsFor({ extraPrincipal: "-5" }).extraPrincipal).toBeDefined();
    expect(errorsFor({ extraPrincipal: "1.001" }).extraPrincipal).toBeDefined();
  });

  it("rejects a payoff date before the next payment date (3.5)", () => {
    // Next payment date is 2024-02-15.
    expect(errorsFor({ payoffDate: "2024-02-14" }).payoffDate).toBeDefined();
    expect(errorsFor({ payoffDate: "2024-02-15" }).payoffDate).toBeUndefined();
    expect(errorsFor({ payoffDate: "2030-01-01" }).payoffDate).toBeUndefined();
    expect(errorsFor({ payoffDate: "2024-02-30" }).payoffDate).toBeDefined();
  });

  it("clamps the next payment date from the anchor day (3.5)", () => {
    const patch = { anchorDate: "2024-01-31" };
    expect(errorsFor({ ...patch, payoffDate: "2024-02-28" }).payoffDate).toBeDefined();
    expect(errorsFor({ ...patch, payoffDate: "2024-02-29" }).payoffDate).toBeUndefined();
  });

  it("validates original principal as optional and positive (4.2)", () => {
    expect(errorsFor({ originalPrincipal: "" }).originalPrincipal).toBeUndefined();
    expect(errorsFor({ originalPrincipal: "300000.00" }).originalPrincipal).toBeUndefined();
    expect(errorsFor({ originalPrincipal: "0" }).originalPrincipal).toBeDefined();
    expect(errorsFor({ originalPrincipal: "1.234" }).originalPrincipal).toBeDefined();
    expect(errorsFor({ originalPrincipal: "1000000000" }).originalPrincipal).toBeDefined();
  });

  it("checks closing date format only, with no relation to other dates (4.4)", () => {
    expect(errorsFor({ closingDate: "nope" }).closingDate).toBeDefined();
    expect(errorsFor({ closingDate: "2022-02-30" }).closingDate).toBeDefined();
    expect(errorsFor({ closingDate: "2022-02-14" }).closingDate).toBeUndefined();
    expect(errorsFor({ closingDate: "2099-01-01" }).closingDate).toBeUndefined();
  });
});

describe("toLoanInput", () => {
  it("keeps money and rate as strings and canonicalizes the rate", () => {
    const input = toLoanInput({ ...valid, description: "  Main mortgage " });
    expect(input).toEqual({
      description: "Main mortgage",
      annual_interest_rate: "6.875",
      monthly_payment: "1500.00",
      anchor_balance: "200000.00",
      anchor_date: "2024-01-15",
      extra_principal: "0.00",
      payoff_date: null,
      original_principal: null,
      closing_date: null,
      include_in_report: true,
    });
    expect(typeof input.monthly_payment).toBe("string");
    expect(typeof input.anchor_balance).toBe("string");
  });

  it("passes optional values through as strings", () => {
    const input = toLoanInput({
      ...valid,
      extraPrincipal: "50.50",
      originalPrincipal: "300000.00",
      closingDate: "2022-02-14",
      payoffDate: "2040-01-01",
      includeInReport: false,
    });
    expect(input.extra_principal).toBe("50.50");
    expect(input.original_principal).toBe("300000.00");
    expect(input.closing_date).toBe("2022-02-14");
    expect(input.payoff_date).toBe("2040-01-01");
    expect(input.include_in_report).toBe(false);
  });

  it.each([
    ["6", "6"],
    ["0.0000", "0"],
    ["100.0000", "100"],
    ["0.5000", "0.5"],
  ])("canonicalizes rate %s to %s", (raw, expected) => {
    expect(toLoanInput({ ...valid, annualInterestRate: raw }).annual_interest_rate).toBe(expected);
  });
});
