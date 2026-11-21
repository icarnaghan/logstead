/**
 * Itemized expenses API module.
 *
 * Typed wrapper over the shared {@link apiClient} for the per-category
 * itemized expense routes under
 * `/properties/{propertyId}/itemized/{categoryId}` (Requirements 2.1, 8.2,
 * 9.5, 11.2, 14.1). Money is a fixed two-decimal string end to end.
 *
 * Receipts for an entry or total row reuse the transactions receipt routes,
 * so they are not part of this module.
 */

import { apiClient, type ApiClient } from "../lib/apiClient";
import type { Transaction } from "./transactions";

/** Which source supplies the line total for the year. */
export type ItemizedLineSource = "entered_total" | "itemized" | "none";

/** Year summary for one itemized category on a property. */
export interface ItemizedSummary {
  readonly category_id: string;
  readonly label: string;
  readonly schedule_e_line: number;
  readonly tax_year: number;
  /** Sum of entered total rows; null when no total exists. */
  readonly entered_total: string | null;
  readonly entered_total_rows: Transaction[];
  readonly itemized_sum: string;
  readonly itemized_count: number;
  /** Itemized entries, newest first. */
  readonly entries: Transaction[];
  /** entered_total - itemized_sum; null when no total exists. */
  readonly remainder: string | null;
  readonly line_total: string;
  readonly line_source: ItemizedLineSource;
  readonly total_differs_from_itemized: boolean;
}

/** Request body for creating or editing an itemized entry. */
export interface ItemizedEntryInput {
  /** ISO date (YYYY-MM-DD). */
  date: string;
  /** Money as a fixed two-decimal string, greater than zero. */
  amount: string;
  /** Description / vendor, 1 to 200 characters. */
  description: string;
  /** Optional notes, up to 1000 characters. */
  notes?: string;
}

function categoryPath(propertyId: string, categoryId: string): string {
  return `/properties/${encodeURIComponent(propertyId)}/itemized/${encodeURIComponent(categoryId)}`;
}

function entriesPath(propertyId: string, categoryId: string): string {
  return `${categoryPath(propertyId, categoryId)}/entries`;
}

function totalPath(propertyId: string, categoryId: string): string {
  return `${categoryPath(propertyId, categoryId)}/total`;
}

/** The itemized expenses API surface, with an injectable client for tests. */
export class ItemizedApi {
  private readonly client: ApiClient;

  constructor(client: ApiClient = apiClient) {
    this.client = client;
  }

  /** Summary for a category and tax year (`taxYear` is required). */
  getSummary(
    propertyId: string,
    categoryId: string,
    taxYear: number,
    signal?: AbortSignal,
  ): Promise<ItemizedSummary> {
    return this.client.get<ItemizedSummary>(
      categoryPath(propertyId, categoryId),
      { query: { taxYear }, signal },
    );
  }

  /** Create an itemized entry. */
  createEntry(
    propertyId: string,
    categoryId: string,
    input: ItemizedEntryInput,
    signal?: AbortSignal,
  ): Promise<Transaction> {
    return this.client.post<Transaction>(entriesPath(propertyId, categoryId), {
      body: input,
      signal,
    });
  }

  /** Edit an itemized entry. */
  updateEntry(
    propertyId: string,
    categoryId: string,
    entryId: string,
    input: ItemizedEntryInput,
    signal?: AbortSignal,
  ): Promise<Transaction> {
    return this.client.put<Transaction>(
      `${entriesPath(propertyId, categoryId)}/${encodeURIComponent(entryId)}`,
      { body: input, signal },
    );
  }

  /** Delete an itemized entry and its receipts. */
  deleteEntry(
    propertyId: string,
    categoryId: string,
    entryId: string,
    signal?: AbortSignal,
  ): Promise<void> {
    return this.client.delete<void>(
      `${entriesPath(propertyId, categoryId)}/${encodeURIComponent(entryId)}`,
      { signal },
    );
  }

  /** Create or update the single entered total for a year, in place. */
  setTotal(
    propertyId: string,
    categoryId: string,
    taxYear: number,
    amount: string,
    signal?: AbortSignal,
  ): Promise<ItemizedSummary> {
    return this.client.put<ItemizedSummary>(totalPath(propertyId, categoryId), {
      body: { tax_year: taxYear, amount },
      signal,
    });
  }

  /** Remove the single entered total for a year. */
  removeTotal(
    propertyId: string,
    categoryId: string,
    taxYear: number,
    signal?: AbortSignal,
  ): Promise<ItemizedSummary> {
    return this.client.delete<ItemizedSummary>(
      totalPath(propertyId, categoryId),
      { query: { taxYear }, signal },
    );
  }
}

/** Shared instance wired to the app's singleton API client. */
export const itemizedApi = new ItemizedApi();
