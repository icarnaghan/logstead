/**
 * Passive loss carryforward API module.
 *
 * Thin, typed wrapper over the shared {@link apiClient} for the portfolio-level
 * carryforward reconciliation (Requirements 1, 3, 4). It covers the backend's
 * read/write routes:
 *  - `GET /carryforward` → the full {@link ReconciliationSummary},
 *  - `PUT /carryforward/years/{taxYear}` → set a year's Reported_Carryforward
 *    and/or its Allowed_Loss / Fully_Allowed (whichever keys the body carries),
 *  - `DELETE /carryforward/years/{taxYear}` → clear a year's Reported_Carryforward,
 *  - `PUT /carryforward/opening-balance` → set the Opening_Balance.
 *
 * Money is represented as fixed two-decimal **strings** end-to-end (never
 * floating point), matching the backend contract. The Schedule E net may be
 * negative — a two-decimal string like "-125.00" — denoting a loss; expected
 * and opening amounts are non-negative. The module is transport-only: it holds
 * no UI state and accepts an injectable client so it is easy to unit test
 * without a network.
 */

import { apiClient, type ApiClient } from "../lib/apiClient";

/**
 * One reconciled tax year in the carryforward series (Requirements 1, 3, 4).
 *
 * `schedule_e_net` is the derived portfolio Schedule E net for the year — a
 * two-decimal string, negative when the portfolio ran at a loss.
 *
 * Carry-in vs carry-out: `reported_carryforward` is the Form 8582 "Prior years
 * unallowed losses" figure the user recorded for the year (the balance carried
 * INTO the year), or null when unreported. `expected_carry_in` is the balance
 * expected to enter the year and is what the reported figure is compared with.
 * `expected_carryforward` is the expected carry-OUT (the balance expected to
 * leave the year, i.e. the next year's expected carry-in). The wire names are
 * asymmetric on purpose to keep existing consumers working.
 *
 * `allowed_loss` is the portion of the year's loss the user recorded as allowed
 * (deducted) on their filed return, and `fully_allowed` flags that the whole
 * loss was allowed; both change this year's carry-out. `status` flags whether
 * reported and expected carry-in agree (within the status tolerance), diverge,
 * or are unreported.
 *
 * `status` is `carried` when the reported carry-in disagrees with the expected
 * carry-in (beyond the status tolerance) but matches, within the tolerance, the
 * prior year's step applied to the prior year's reported carry-in (the year
 * merely inherited an earlier error). `drift` is the exact, untoleranced
 * `reported_carryforward - expected_carry_in` as a signed two-decimal string
 * (null when unreported), and `carried_from_year` names the root-cause tax year
 * for a `carried` year (null otherwise, or when no earlier mismatch year is
 * known).
 */
export interface ReconciledYear {
  /** The four-digit tax year these figures are derived for. */
  readonly tax_year: number;
  /** Fixed two-decimal string; negative denotes a loss, e.g. "-125.00". */
  readonly schedule_e_net: string;
  /** Expected carry-OUT: balance expected to leave the year. Non-negative, e.g. "500.00". */
  readonly expected_carryforward: string;
  /**
   * Carry-IN reported: the Form 8582 "Prior years unallowed losses" figure,
   * fixed two-decimal string, or null when unreported.
   */
  readonly reported_carryforward: string | null;
  /**
   * Balance expected to enter the year (what `reported_carryforward` is
   * compared with). Fixed two-decimal string, non-negative.
   */
  readonly expected_carry_in: string;
  /** Fixed two-decimal string, non-negative; "0.00" when none recorded. */
  readonly allowed_loss: string;
  /** True when the user recorded the whole loss as allowed for the year. */
  readonly fully_allowed: boolean;
  /** Reconciliation state for the year. */
  readonly status: "ok" | "mismatch" | "carried" | "unreported";
  /** Signed two-decimal string (reported - expected), or null when unreported. */
  readonly drift: string | null;
  /** For a `carried` year, the root-cause tax year; otherwise null. */
  readonly carried_from_year: number | null;
}

/**
 * The full carryforward reconciliation series for the user's portfolio
 * (Requirements 1, 3, 4). Years are ascending by `tax_year`. `has_data` is
 * false when the user has no Data_Years and no opening balance.
 */
export interface ReconciliationSummary {
  /** One row per Data_Year, ascending by `tax_year`. */
  readonly years: readonly ReconciledYear[];
  /** Fixed two-decimal string, non-negative. The starting suspended balance. */
  readonly opening_balance: string;
  /** False when there are no Data_Years and no opening balance. */
  readonly has_data: boolean;
  /** Latest Data_Year + 1, or null when there are no years. */
  readonly next_year: number | null;
  /**
   * Fixed two-decimal string: the balance expected to carry into `next_year`
   * (what the next return's prior-years line should show). Equals the opening
   * balance when there are no years.
   */
  readonly next_year_expected_carry_in: string;
  /**
   * Fixed two-decimal string, e.g. "2.00": the largest absolute difference, in
   * dollars, between a reported carry-in and an expected or chain figure that
   * still counts as a match. Returns are filed in whole dollars, so the status
   * comparison allows this much slack. `drift` stays exact.
   */
  readonly status_tolerance: string;
}

/**
 * The carryforward API surface. An injectable {@link ApiClient} keeps it
 * unit-testable; the default export wires the shared singleton.
 */
export class CarryforwardApi {
  private readonly client: ApiClient;

  constructor(client: ApiClient = apiClient) {
    this.client = client;
  }

  /**
   * Fetch the full carryforward reconciliation series for the portfolio
   * (Requirement 1.4). Money fields on the returned {@link ReconciliationSummary}
   * are fixed two-decimal strings end-to-end.
   */
  getReconciliation(signal?: AbortSignal): Promise<ReconciliationSummary> {
    return this.client.get<ReconciliationSummary>("/carryforward", { signal });
  }

  /**
   * Partially update a tax year via `PUT /carryforward/years/{taxYear}`,
   * sending only the fields present in `patch` (Requirements 1.6, 6.4). The
   * backend reads whichever keys are present: `amount` sets the
   * Reported_Carryforward, `allowed_loss` sets the Allowed_Loss (or clears it
   * when `null`), and `fully_allowed` toggles the Fully_Allowed flag. Omitted
   * keys are left untouched. Money values are fixed two-decimal strings, never
   * numbers.
   */
  setYear(
    taxYear: number,
    patch: {
      amount?: string;
      allowed_loss?: string | null;
      fully_allowed?: boolean;
    },
    signal?: AbortSignal,
  ): Promise<void> {
    return this.client.put<void>(
      `/carryforward/years/${encodeURIComponent(taxYear)}`,
      { body: patch, signal },
    );
  }

  /**
   * Record the user's reported carry-in (Form 8582 "Prior years unallowed
   * losses") for a tax year (Requirement 3.6).
   * `amount` is a fixed two-decimal money string. Thin wrapper over
   * {@link setYear} that sends only `amount`.
   */
  setReported(
    taxYear: number,
    amount: string,
    signal?: AbortSignal,
  ): Promise<void> {
    return this.setYear(taxYear, { amount }, signal);
  }

  /**
   * Record the user's Allowed_Loss for a tax year (Requirements 1.6, 6.4).
   * `amount` is a fixed two-decimal, non-negative money string.
   */
  setAllowedLoss(
    taxYear: number,
    amount: string,
    signal?: AbortSignal,
  ): Promise<void> {
    return this.setYear(taxYear, { allowed_loss: amount }, signal);
  }

  /**
   * Clear the user's Allowed_Loss for a tax year (Requirements 1.6, 6.4). Sends
   * `allowed_loss: null` to explicitly clear it while preserving the year's
   * other recorded fields.
   */
  clearAllowedLoss(taxYear: number, signal?: AbortSignal): Promise<void> {
    return this.setYear(taxYear, { allowed_loss: null }, signal);
  }

  /**
   * Toggle the Fully_Allowed flag for a tax year (Requirements 1.6, 6.4): when
   * `on`, the whole loss is treated as allowed for the year.
   */
  setFullyAllowed(
    taxYear: number,
    on: boolean,
    signal?: AbortSignal,
  ): Promise<void> {
    return this.setYear(taxYear, { fully_allowed: on }, signal);
  }

  /**
   * Clear the user's Reported_Carryforward for a tax year (Requirement 3.6).
   */
  clearReported(taxYear: number, signal?: AbortSignal): Promise<void> {
    return this.client.delete<void>(
      `/carryforward/years/${encodeURIComponent(taxYear)}`,
      { signal },
    );
  }

  /**
   * Set the portfolio's Opening_Balance (Requirement 4.1). `amount` is a fixed
   * two-decimal, non-negative money string.
   */
  setOpeningBalance(amount: string, signal?: AbortSignal): Promise<void> {
    return this.client.put<void>("/carryforward/opening-balance", {
      body: { amount },
      signal,
    });
  }
}

/** Shared instance wired to the app's singleton API client. */
export const carryforwardApi = new CarryforwardApi();

/** Fetch the full carryforward reconciliation series (Requirement 1.4). */
export function getReconciliation(
  signal?: AbortSignal,
): Promise<ReconciliationSummary> {
  return carryforwardApi.getReconciliation(signal);
}

/** Record the Reported_Carryforward for a tax year (Requirement 3.6). */
export function setReported(
  taxYear: number,
  amount: string,
  signal?: AbortSignal,
): Promise<void> {
  return carryforwardApi.setReported(taxYear, amount, signal);
}

/** Clear the Reported_Carryforward for a tax year (Requirement 3.6). */
export function clearReported(
  taxYear: number,
  signal?: AbortSignal,
): Promise<void> {
  return carryforwardApi.clearReported(taxYear, signal);
}

/** Record the Allowed_Loss for a tax year (Requirements 1.6, 6.4). */
export function setAllowedLoss(
  taxYear: number,
  amount: string,
  signal?: AbortSignal,
): Promise<void> {
  return carryforwardApi.setAllowedLoss(taxYear, amount, signal);
}

/** Clear the Allowed_Loss for a tax year (Requirements 1.6, 6.4). */
export function clearAllowedLoss(
  taxYear: number,
  signal?: AbortSignal,
): Promise<void> {
  return carryforwardApi.clearAllowedLoss(taxYear, signal);
}

/** Toggle the Fully_Allowed flag for a tax year (Requirements 1.6, 6.4). */
export function setFullyAllowed(
  taxYear: number,
  on: boolean,
  signal?: AbortSignal,
): Promise<void> {
  return carryforwardApi.setFullyAllowed(taxYear, on, signal);
}

/** Set the portfolio's Opening_Balance (Requirement 4.1). */
export function setOpeningBalance(
  amount: string,
  signal?: AbortSignal,
): Promise<void> {
  return carryforwardApi.setOpeningBalance(amount, signal);
}
