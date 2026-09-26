/**
 * Dashboard API module.
 *
 * Thin, typed wrapper over the shared {@link apiClient} for the numeric
 * portfolio dashboard (Requirement 11). It covers the two read-only routes the
 * backend exposes (task 16.1):
 *  - `GET /dashboard?taxYear=<year>` → a full {@link DashboardSummary}
 *    (portfolio totals + per-property breakdown + empty-state prompt),
 *  - `GET /dashboard/properties?taxYear=<year>` → just the per-property list.
 *
 * Money is represented as fixed two-decimal **strings** end-to-end (never
 * floating point), matching the backend contract (Requirement 13.3). A net may
 * be negative — a two-decimal string like "-125.00" — denoting a loss. The
 * module is transport-only: it holds no UI state and accepts an injectable
 * client so it is easy to unit test without a network.
 */

import { apiClient, type ApiClient } from "../lib/apiClient";

/**
 * One property's income / expense / net for a tax year (Requirement 11.2).
 *
 * Every monetary figure is a fixed two-decimal string. `net` equals
 * `total_income - total_expenses` and is negative when the property ran at a
 * loss for the year.
 */
export interface PropertySummary {
  readonly property_id: string;
  readonly property_name: string;
  /** Fixed two-decimal string, e.g. "1500.00". */
  readonly total_income: string;
  /** Fixed two-decimal string, e.g. "250.00". */
  readonly total_expenses: string;
  /** Fixed two-decimal string; negative denotes a loss, e.g. "-125.00". */
  readonly net: string;
}

/**
 * The numeric dashboard summary for a user + tax year (Requirement 11).
 *
 * Carries the portfolio totals (Requirement 11.1), the per-property breakdown
 * (Requirement 11.2), and the empty-state flag/prompt (Requirement 11.4). No
 * chart or visualization data is included — numeric summaries only.
 */
export interface DashboardSummary {
  /** The tax year every figure is derived for (Requirement 11.3). */
  readonly tax_year: number;
  /** False when the user owns no properties (Requirement 11.4). */
  readonly has_properties: boolean;
  /** Portfolio total income (sum of per-property income). */
  readonly total_income: string;
  /** Portfolio total expenses (sum of per-property expenses). */
  readonly total_expenses: string;
  /** Portfolio net = sum of the per-property nets; negative denotes a loss. */
  readonly net: string;
  /** Per-property summaries, in the order the property service lists them. */
  readonly properties: readonly PropertySummary[];
  /**
   * The add-first-property guidance when `has_properties` is false; otherwise
   * null (Requirement 11.4).
   */
  readonly empty_state_prompt?: string | null;
}

/**
 * The dashboard API surface. An injectable {@link ApiClient} keeps it
 * unit-testable; the default export wires the shared singleton.
 */
export class DashboardApi {
  private readonly client: ApiClient;

  constructor(client: ApiClient = apiClient) {
    this.client = client;
  }

  /**
   * Fetch the full numeric dashboard summary for a tax year (Requirement 11).
   * Omitting `taxYear` lets the backend default to the current tax year
   * (Requirement 11.3); supplying it re-derives every figure for that year.
   */
  getDashboard(taxYear?: number, signal?: AbortSignal): Promise<DashboardSummary> {
    return this.client.get<DashboardSummary>("/dashboard", {
      query: taxYear === undefined ? undefined : { taxYear },
      signal,
    });
  }

  /**
   * Fetch just the per-property income / expense / net breakdown for a tax
   * year (Requirement 11.2). Provided for completeness; the page derives its
   * per-property table from {@link getDashboard}.
   */
  getPropertySummaries(
    taxYear?: number,
    signal?: AbortSignal,
  ): Promise<PropertySummary[]> {
    return this.client.get<PropertySummary[]>("/dashboard/properties", {
      query: taxYear === undefined ? undefined : { taxYear },
      signal,
    });
  }
}

/** Shared instance wired to the app's singleton API client. */
export const dashboardApi = new DashboardApi();
