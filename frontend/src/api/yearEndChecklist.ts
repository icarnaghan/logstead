/**
 * Year-end checklist API module.
 *
 * Thin, typed wrapper over the shared {@link apiClient} for the read-only
 * checklist routes:
 *  - `GET /properties/{propertyId}/checklist?taxYear=` → {@link YearEndChecklist},
 *  - `GET /properties/{propertyId}/checklist/summary` → {@link PropertyChecklistSummary},
 *  - `GET /checklist/summary?taxYear=` → {@link PortfolioChecklistSummary}.
 *
 * Money values inside `details` and `thresholds` are fixed two-decimal strings,
 * never numbers. `details` stays loosely typed; the UI narrows it per item id.
 */

import { apiClient, type ApiClient } from "../lib/apiClient";

export type ChecklistStatus = "done" | "needs_attention" | "not_applicable";

export interface ChecklistCounts {
  readonly done: number;
  readonly needs_attention: number;
  readonly not_applicable: number;
  readonly total: number;
}

export interface ChecklistItem {
  readonly id: string;
  readonly title: string;
  readonly status: ChecklistStatus;
  readonly reason: string;
  /** App path of the page that fixes the item. */
  readonly link: string;
  readonly details?: Record<string, unknown> | null;
}

export interface YearEndChecklist {
  readonly property_id: string;
  readonly tax_year: number;
  readonly thresholds: Record<string, string | number>;
  readonly counts: ChecklistCounts;
  readonly items: readonly ChecklistItem[];
}

export interface PropertyChecklistSummary {
  readonly property_id: string;
  /** Newest year first. */
  readonly years: readonly {
    readonly tax_year: number;
    readonly counts: ChecklistCounts;
  }[];
}

export interface PortfolioChecklistSummary {
  readonly tax_year: number;
  readonly properties: readonly {
    readonly property_id: string;
    readonly property_name: string;
    readonly counts: ChecklistCounts;
  }[];
}

function yearQuery(taxYear: number | null | undefined) {
  return taxYear === undefined || taxYear === null ? undefined : { taxYear };
}

export class YearEndChecklistApi {
  private readonly client: ApiClient;

  constructor(client: ApiClient = apiClient) {
    this.client = client;
  }

  /** Fetch one property's checklist for a tax year. */
  getChecklist(
    propertyId: string,
    taxYear: number | null | undefined,
    signal?: AbortSignal,
  ): Promise<YearEndChecklist> {
    return this.client.get<YearEndChecklist>(
      `/properties/${encodeURIComponent(propertyId)}/checklist`,
      { query: yearQuery(taxYear), signal },
    );
  }

  /** Fetch per-year counts for a property's most recent Data_Years. */
  getPropertySummary(
    propertyId: string,
    signal?: AbortSignal,
  ): Promise<PropertyChecklistSummary> {
    return this.client.get<PropertyChecklistSummary>(
      `/properties/${encodeURIComponent(propertyId)}/checklist/summary`,
      { signal },
    );
  }

  /** Fetch per-property counts for one tax year (server default when omitted). */
  getPortfolioSummary(
    taxYear: number | null | undefined,
    signal?: AbortSignal,
  ): Promise<PortfolioChecklistSummary> {
    return this.client.get<PortfolioChecklistSummary>("/checklist/summary", {
      query: yearQuery(taxYear),
      signal,
    });
  }
}

/** Shared instance wired to the app's singleton API client. */
export const yearEndChecklistApi = new YearEndChecklistApi();
