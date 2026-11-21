/**
 * Global search API module.
 *
 * Thin, typed wrapper over the shared {@link apiClient} for `GET /search`
 * (Requirements 8.1, 8.6, 11.1). Money is a fixed two-decimal string. Requests
 * are abortable through an `AbortSignal`.
 */

import { apiClient, type ApiClient } from "../lib/apiClient";

/** The kinds of record a search can return. */
export type SearchKind = string;

/** One matching record. */
export interface SearchHit {
  readonly kind: SearchKind;
  readonly id: string;
  readonly property_id: string | null;
  readonly title: string;
  readonly subtitle: string | null;
  readonly matched_field: string;
  /** In-app link to the record. */
  readonly link: string;
  /** Fixed two-decimal string, or null. */
  readonly amount: string | null;
  /** ISO date (YYYY-MM-DD), or null. */
  readonly date: string | null;
}

/** Hits of one kind with the total number of matches. */
export interface SearchGroup {
  readonly kind: SearchKind;
  readonly total: number;
  readonly hits: readonly SearchHit[];
}

/** The `GET /search` response body. */
export interface SearchResponse {
  readonly query: string;
  readonly groups: readonly SearchGroup[];
  /** True when the scan cap was reached and results may be incomplete. */
  readonly truncated: boolean;
  readonly scanned: number;
}

/** Optional parameters of {@link SearchApi.search}. */
export interface SearchOptions {
  readonly limit?: number;
  readonly propertyId?: string;
  readonly signal?: AbortSignal;
}

export class SearchApi {
  private readonly client: ApiClient;

  constructor(client: ApiClient = apiClient) {
    this.client = client;
  }

  /** Search the signed-in user's records for `q`. */
  search(q: string, options: SearchOptions = {}): Promise<SearchResponse> {
    const { limit, propertyId, signal } = options;
    const query: Record<string, string | number> = { q };
    if (limit !== undefined) query.limit = limit;
    if (propertyId !== undefined) query.propertyId = propertyId;
    return this.client.get<SearchResponse>("/search", { query, signal });
  }
}

/** Shared instance wired to the app's singleton API client. */
export const searchApi = new SearchApi();
