import type { LoanInput } from "../../api/loans";
import { projectLoan } from "../../lib/amortization";

/**
 * Form state, client-side validation and payload mapping for the Loan form.
 *
 * Validation mirrors the backend `validate_loan_fields` grammar for the
 * balance-anchor model (Requirements 1.2-1.8, 2.14, 2.15, 3.2, 3.5, 4.2, 4.4).
 * All form values are strings; money and the interest rate are never coerced
 * to `number` and are sent as strings.
 */

/** All Loan form values, held as strings exactly as typed. */
export interface LoanFormValues {
  description: string;
  annualInterestRate: string;
  monthlyPayment: string;
  anchorBalance: string;
  anchorDate: string;
  extraPrincipal: string;
  payoffDate: string;
  originalPrincipal: string;
  closingDate: string;
  includeInReport: boolean;
}

/** Keys that can carry a field-level error. */
export type LoanFormField = Exclude<keyof LoanFormValues, "includeInReport">;

/** Per-field messages, plus an optional form-level message. */
export type LoanFormErrors = Partial<Record<LoanFormField | "form", string>>;

/** Maps backend `field` names onto form field keys. */
export const LOAN_FIELD_BY_API_NAME: Record<string, LoanFormField> = {
  description: "description",
  annual_interest_rate: "annualInterestRate",
  monthly_payment: "monthlyPayment",
  anchor_balance: "anchorBalance",
  anchor_date: "anchorDate",
  extra_principal: "extraPrincipal",
  payoff_date: "payoffDate",
  original_principal: "originalPrincipal",
  closing_date: "closingDate",
};

/** Today's local date as `YYYY-MM-DD`. The clock is injectable for tests. */
export function todayIso(now: Date = new Date()): string {
  const p = (n: number, w: number) => String(n).padStart(w, "0");
  return `${p(now.getFullYear(), 4)}-${p(now.getMonth() + 1, 2)}-${p(now.getDate(), 2)}`;
}

/** An empty form whose anchor date defaults to `today` (Requirement 10.2). */
export function emptyLoanForm(today: string = todayIso()): LoanFormValues {
  return {
    description: "",
    annualInterestRate: "",
    monthlyPayment: "",
    anchorBalance: "",
    anchorDate: today,
    extraPrincipal: "",
    payoffDate: "",
    originalPrincipal: "",
    closingDate: "",
    includeInReport: true,
  };
}

export const EMPTY_LOAN_FORM: LoanFormValues = emptyLoanForm();

const MAX_MONEY_CENTS = 99_999_999_999n; // 999,999,999.99
const MAX_RATE_SCALED = 1_000_000n; // 100.0000 at 4 dp
const MIN_DATE = "1900-01-01";
const MAX_PAYMENTS = 600;
const MAX_YEAR = 9999;

/** Parse a non-negative decimal with at most `maxDp` decimals, scaled by 10^maxDp. */
function parseScaled(raw: string, maxDp: number): bigint | null {
  const match = new RegExp(`^(\\d+)(?:\\.(\\d{1,${maxDp}}))?$`).exec(raw.trim());
  if (!match) return null;
  return BigInt(match[1] + (match[2] ?? "").padEnd(maxDp, "0"));
}

/** Strict `YYYY-MM-DD` that is also a real calendar date; returns [y, m, d] or null. */
function parseIsoDate(raw: string): [number, number, number] | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  if (!match) return null;
  const y = Number(match[1]);
  const m = Number(match[2]);
  const d = Number(match[3]);
  const probe = new Date(Date.UTC(2000, m - 1, d));
  probe.setUTCFullYear(y);
  if (
    probe.getUTCFullYear() !== y ||
    probe.getUTCMonth() !== m - 1 ||
    probe.getUTCDate() !== d
  ) {
    return null;
  }
  return [y, m, d];
}

function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(2001, month, 0)).getUTCDate() +
    (month === 2 && ((year % 4 === 0 && year % 100 !== 0) || year % 400 === 0) ? 1 : 0);
}

/** Date of payment `k` (>= 1) after the anchor, clamped from the anchor day. */
function paymentDateParts(
  anchor: [number, number, number],
  k: number,
): [number, number, number] {
  const m0 = anchor[1] - 1 + k;
  const year = anchor[0] + Math.floor(m0 / 12);
  const month = (m0 % 12) + 1;
  return [year, month, Math.min(anchor[2], daysInMonth(year, month))];
}

function formatParts([y, m, d]: [number, number, number]): string {
  const p = (n: number, w: number) => String(n).padStart(w, "0");
  return `${p(y, 4)}-${p(m, 2)}-${p(d, 2)}`;
}

/** Validate every field; returns an empty object when the form is valid. */
export function validateLoanForm(values: LoanFormValues): LoanFormErrors {
  const errors: LoanFormErrors = {};

  const description = values.description.trim();
  if (description.length < 1 || description.length > 200) {
    errors.description = "Description must be 1 to 200 characters.";
  }

  const rate = parseScaled(values.annualInterestRate, 4);
  if (rate === null || rate > MAX_RATE_SCALED) {
    errors.annualInterestRate =
      "Annual interest rate must be between 0 and 100, with at most 4 decimals.";
  }

  const payment = parseScaled(values.monthlyPayment, 2);
  if (payment === null || payment <= 0n || payment > MAX_MONEY_CENTS) {
    errors.monthlyPayment =
      "Monthly payment must be greater than 0 and at most 999,999,999.99, with at most 2 decimals.";
  }

  const balance = parseScaled(values.anchorBalance, 2);
  if (balance === null || balance <= 0n || balance > MAX_MONEY_CENTS) {
    errors.anchorBalance =
      "Anchor balance must be greater than 0 and at most 999,999,999.99, with at most 2 decimals.";
  }

  const anchorText = values.anchorDate;
  const anchor = parseIsoDate(anchorText);
  if (!anchor) {
    errors.anchorDate = "Anchor date must be a valid date (YYYY-MM-DD).";
  } else if (anchorText < MIN_DATE) {
    errors.anchorDate = "Anchor date must be on or after 1900-01-01.";
  }

  // The payment must exceed one month of interest on the anchor balance.
  if (
    !errors.annualInterestRate &&
    !errors.monthlyPayment &&
    !errors.anchorBalance &&
    payment !== null &&
    balance !== null &&
    rate !== null
  ) {
    const denom = 12_000_000n;
    const interest = (2n * balance * rate + denom) / (2n * denom);
    if (payment <= interest) {
      errors.monthlyPayment =
        "Monthly payment must exceed the first month's interest.";
    }
  }

  const extraText = values.extraPrincipal.trim();
  if (extraText) {
    const extra = parseScaled(extraText, 2);
    if (extra === null || extra > MAX_MONEY_CENTS) {
      errors.extraPrincipal =
        "Extra principal must be 0 or more and at most 999,999,999.99, with at most 2 decimals.";
    }
  }

  const original = values.originalPrincipal.trim();
  if (original) {
    const cents = parseScaled(original, 2);
    if (cents === null || cents <= 0n || cents > MAX_MONEY_CENTS) {
      errors.originalPrincipal =
        "Original principal must be greater than 0 and at most 999,999,999.99, with at most 2 decimals.";
    }
  }

  // Informational: format only, no relation to any other date.
  const closing = values.closingDate.trim();
  if (closing && !parseIsoDate(closing)) {
    errors.closingDate = "Closing date must be a valid date (YYYY-MM-DD).";
  }

  const payoff = values.payoffDate.trim();
  if (payoff) {
    if (!parseIsoDate(payoff)) {
      errors.payoffDate = "Payoff date must be a valid date (YYYY-MM-DD).";
    } else if (anchor && !errors.anchorDate) {
      const next = paymentDateParts(anchor, 1);
      if (next[0] <= MAX_YEAR && payoff < formatParts(next)) {
        errors.payoffDate =
          "Payoff date must not be before the next payment date.";
      }
    }
  }

  // Whole-schedule checks (600-row cap, year 9999) once every field is valid.
  if (Object.keys(errors).length === 0 && anchor) {
    const projection = projectLoan({
      anchorBalance: values.anchorBalance,
      annualInterestRate: values.annualInterestRate,
      monthlyPayment: values.monthlyPayment,
      extraPrincipal: values.extraPrincipal,
      anchorDate: values.anchorDate,
      payoffDate: values.payoffDate,
    });
    if (projection === null) {
      // Mirror the engine order: the date check precedes the row cap per row.
      for (let k = 1; k <= MAX_PAYMENTS + 1; k += 1) {
        if (paymentDateParts(anchor, k)[0] > MAX_YEAR) {
          errors.anchorDate = "The last payment would fall after year 9999.";
          break;
        }
        if (k > MAX_PAYMENTS) {
          errors.monthlyPayment =
            "This loan would take more than 600 payments to pay off.";
        }
      }
    }
  }

  return errors;
}

/**
 * Build the API payload. Call only after {@link validateLoanForm} returns no
 * errors. Blank optional fields become `null` (dates, original principal) or
 * "0.00" (extra principal); money and the rate stay strings, the rate
 * canonicalized (trailing zeros dropped, e.g. "6.8750" becomes "6.875").
 */
export function toLoanInput(values: LoanFormValues): LoanInput {
  const orNull = (v: string) => (v.trim() ? v.trim() : null);
  return {
    description: values.description.trim(),
    annual_interest_rate: canonicalRate(values.annualInterestRate),
    monthly_payment: values.monthlyPayment.trim(),
    anchor_balance: values.anchorBalance.trim(),
    anchor_date: values.anchorDate.trim(),
    extra_principal: values.extraPrincipal.trim() || "0.00",
    payoff_date: orNull(values.payoffDate),
    original_principal: orNull(values.originalPrincipal),
    closing_date: orNull(values.closingDate),
    include_in_report: values.includeInReport,
  };
}

function canonicalRate(raw: string): string {
  const text = raw.trim();
  if (!text.includes(".")) return text;
  const trimmed = text.replace(/0+$/, "").replace(/\.$/, "");
  return trimmed === "" ? "0" : trimmed;
}
