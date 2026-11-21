/**
 * Mortgage loans API module.
 *
 * Typed helpers over the shared {@link apiClient} for the per-property loan
 * endpoints (Requirements 8.1, 8.5, 8.6, 9.1). Money values and interest rates
 * are exchanged as strings and never coerced to `number`.
 *
 * Backend routes:
 *  - GET/POST         /properties/{propertyId}/loans
 *  - GET              /properties/{propertyId}/loans/line-12-impact
 *  - GET/PUT/DELETE   /properties/{propertyId}/loans/{loanId}
 *  - GET              /properties/{propertyId}/loans/{loanId}/schedule
 *  - PUT/DELETE       /properties/{propertyId}/loans/{loanId}/interest-overrides/{taxYear}
 */

import { apiClient, type ApiClient } from "../lib/apiClient";

/** A loan as returned by the backend, including derived values. */
export interface Loan {
  id: string;
  property_id: string;
  description: string;
  /** Percent rate string, up to 4 decimals, e.g. "6.875". */
  annual_interest_rate: string;
  /** Two-decimal money string: monthly principal-and-interest payment. */
  monthly_payment: string;
  /** Two-decimal money string: balance after the payment made on anchor_date. */
  anchor_balance: string;
  /** ISO date (YYYY-MM-DD). */
  anchor_date: string;
  extra_principal: string;
  payoff_date: string | null;
  /** Informational two-decimal money string. */
  original_principal: string | null;
  /** Informational ISO date. */
  closing_date: string | null;
  include_in_report: boolean;
  /** Tax-year string -> two-decimal money string. */
  interest_overrides: Record<string, string>;
  remaining_payments: number;
  /** ISO date of the first projected payment. */
  next_payment_date: string;
  /** ISO date of the final payment, or null when a payoff date truncates the schedule. */
  projected_payoff_date: string | null;
  payoff_balance: string | null;
  status: "active" | "ended";
  created_at: string;
  updated_at: string;
}

/** Request body for creating or updating a loan. */
export interface LoanInput {
  description: string;
  annual_interest_rate: string;
  monthly_payment: string;
  anchor_balance: string;
  anchor_date: string;
  extra_principal: string;
  payoff_date: string | null;
  original_principal: string | null;
  closing_date: string | null;
  include_in_report: boolean;
}

/** One monthly row of an amortization schedule. */
export interface PaymentRow {
  number: number;
  date: string;
  payment: string;
  interest: string;
  principal: string;
  balance: string;
}

/** One tax year of a loan schedule. */
export interface YearlyRollup {
  tax_year: number;
  payments: number;
  /** Effective interest (override if present, else estimated). */
  interest: string;
  estimated_interest: string;
  interest_override: string | null;
  variance: string | null;
  principal: string;
  total_paid: string;
  /** Null for an override-only year (no payments). */
  ending_balance: string | null;
}

/** A loan's full amortization schedule and yearly rollups. */
export interface LoanSchedule {
  loan_id: string;
  estimate: boolean;
  payoff_balance: string | null;
  payments: PaymentRow[];
  yearly: YearlyRollup[];
}

/** Per-year Line 12 impact of loans on manually entered mortgage interest. */
export interface Line12ImpactYear {
  tax_year: number;
  loan_interest: string;
  superseded_manual_interest: { amount: string; count: number };
}

function loansPath(propertyId: string): string {
  return `/properties/${encodeURIComponent(propertyId)}/loans`;
}

function loanPath(propertyId: string, loanId: string): string {
  return `${loansPath(propertyId)}/${encodeURIComponent(loanId)}`;
}

function overridePath(
  propertyId: string,
  loanId: string,
  taxYear: number,
): string {
  return `${loanPath(propertyId, loanId)}/interest-overrides/${encodeURIComponent(String(taxYear))}`;
}

/** Lists all loans for a property. */
export function listLoans(
  propertyId: string,
  client: ApiClient = apiClient,
): Promise<Loan[]> {
  return client.get<Loan[]>(loansPath(propertyId));
}

/** Creates a loan for a property. */
export function createLoan(
  propertyId: string,
  input: LoanInput,
  client: ApiClient = apiClient,
): Promise<Loan> {
  return client.post<Loan>(loansPath(propertyId), { body: input });
}

/** Fetches a single loan. */
export function getLoan(
  propertyId: string,
  loanId: string,
  client: ApiClient = apiClient,
): Promise<Loan> {
  return client.get<Loan>(loanPath(propertyId, loanId));
}

/** Updates a loan; the schedule is recomputed server-side. */
export function updateLoan(
  propertyId: string,
  loanId: string,
  input: LoanInput,
  client: ApiClient = apiClient,
): Promise<Loan> {
  return client.put<Loan>(loanPath(propertyId, loanId), { body: input });
}

/** Deletes a loan and its schedule. */
export function deleteLoan(
  propertyId: string,
  loanId: string,
  client: ApiClient = apiClient,
): Promise<void> {
  return client.delete<void>(loanPath(propertyId, loanId));
}

/** Fetches a loan's amortization schedule and yearly rollups. */
export function getLoanSchedule(
  propertyId: string,
  loanId: string,
  client: ApiClient = apiClient,
): Promise<LoanSchedule> {
  return client.get<LoanSchedule>(`${loanPath(propertyId, loanId)}/schedule`);
}

/** Sets the interest override for a tax year (money string, e.g. "7010.12"). */
export function setInterestOverride(
  propertyId: string,
  loanId: string,
  taxYear: number,
  interest: string,
  client: ApiClient = apiClient,
): Promise<YearlyRollup> {
  return client.put<YearlyRollup>(overridePath(propertyId, loanId, taxYear), {
    body: { interest },
  });
}

/** Clears the interest override for a tax year. */
export function clearInterestOverride(
  propertyId: string,
  loanId: string,
  taxYear: number,
  client: ApiClient = apiClient,
): Promise<YearlyRollup | null> {
  return client.delete<YearlyRollup | null>(
    overridePath(propertyId, loanId, taxYear),
  );
}

/** Fetches per-year loan interest and superseded manual Line 12 interest. */
export function getLine12Impact(
  propertyId: string,
  client: ApiClient = apiClient,
): Promise<Line12ImpactYear[]> {
  return client.get<Line12ImpactYear[]>(`${loansPath(propertyId)}/line-12-impact`);
}
