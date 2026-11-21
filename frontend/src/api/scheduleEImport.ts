/**
 * Schedule E Import API module.
 *
 * Typed, transport-only wrapper over the shared {@link apiClient} for the
 * Schedule E Import feature. "Importing a Schedule E" synthesizes the backing
 * transactions for one or more (Property, Tax_Year) pairs from the line amounts
 * the user enters, so this module submits a single multi-property
 * {@link ImportSubmission} and exposes an undo for one (Property, Tax_Year):
 *
 *  - `importScheduleE(submission)`           → `POST /imports/schedule-e`
 *  - `removeScheduleEImport(propertyId, taxYear)`
 *       → `DELETE /imports/schedule-e/{propertyId}/{taxYear}`
 *
 * The backend serializes dataclasses with snake_case field names, so the wire
 * types below mirror that shape exactly: `tax_year`, each entry maps via
 * `property_id` OR `new_property`, and `lines[]` carry a numeric
 * `schedule_e_line`, a money `amount` string, and an optional `description`
 * (Line 19 "Other"). Money and identifiers are strings end-to-end (never
 * floating point, never coerced to numbers), matching the backend contract.
 *
 * By default this module uses the shared `apiClient`. Tests inject a custom
 * {@link ApiClient} (backed by a fake `fetch`) via {@link setScheduleEImportClient}
 * so they can exercise the real request/parse path without hitting the network;
 * {@link resetScheduleEImportClient} restores the shared production client.
 */

import { ApiClient, apiClient, ApiError } from "../lib/apiClient";
import type { PropertyInput } from "./properties";

// Re-export the error class as a value so callers can both catch it
// (`err instanceof ApiError`) and reference its type without importing the
// shared apiClient module directly.
export { ApiError };

// Re-export the inline-create body shape so the import form can map a new
// property for an entry without importing the properties module directly.
export type { PropertyInput };

/**
 * One Schedule E Part I line amount within a {@link PropertyEntryInput}. The
 * amount is money as a fixed two-decimal string (e.g. "1875.50"); a blank/absent
 * amount is treated as zero by the backend. `description` applies to Line 19
 * ("Other") only; when omitted the backend applies a default description.
 */
export interface LineAmountInput {
  /** Schedule E Part I line: 3-4 (income) or 5-17, 19 (expense); never 18. */
  schedule_e_line: number;
  /** Money as a fixed two-decimal string. */
  amount: string;
  /** Free-text description, required/defaulted for Line 19 only. */
  description?: string;
}

/**
 * One property column of the import (the analog of Schedule E Part I column
 * A/B/C). Exactly one of `property_id` (an existing owned property) or
 * `new_property` (inline creation) is set; `lines` carries that property's
 * entered Schedule E line amounts.
 */
export interface PropertyEntryInput {
  /** Map to an existing owned property. */
  property_id?: string;
  /** Create a property inline and map this entry to it. */
  new_property?: PropertyInput;
  lines: LineAmountInput[];
}

/**
 * The whole multi-property, single-year submission: one `tax_year` shared by
 * every entry, and one or more {@link PropertyEntryInput} rows.
 */
export interface ImportSubmission {
  tax_year: number;
  entries: PropertyEntryInput[];
}

/**
 * Per-entry outcome of an import, mirroring the backend `EntryOutcome`
 * dataclass. `property_id` is the resolved id (existing or newly created);
 * `deleted_prior_count` is the number of previously-imported rows replaced for
 * that (Property, Tax_Year).
 */
export interface EntryOutcome {
  property_id: string;
  created_transaction_ids: string[];
  deleted_prior_count: number;
  created_inline_property: boolean;
}

/** The outcome of an import submission, mirroring the backend `ImportOutcome`. */
export interface ImportOutcome {
  tax_year: number;
  entries: EntryOutcome[];
}

/**
 * The outcome of removing the imported set for one (Property, Tax_Year),
 * mirroring the backend `RemoveOutcome`.
 */
export interface RemoveOutcome {
  property_id: string;
  tax_year: number;
  deleted_count: number;
}

// The client is a module-level singleton so components share one instance, but
// tests can swap it for one backed by an injected fetch.
let client: ApiClient = apiClient;

/** Override the API client used by this module (tests inject a fake fetch). */
export function setScheduleEImportClient(next: ApiClient): void {
  client = next;
}

/** Reset back to the shared production client (call in test teardown). */
export function resetScheduleEImportClient(): void {
  client = apiClient;
}

/**
 * Submit a multi-property Schedule E import. Posts the snake_case
 * {@link ImportSubmission} body to `/imports/schedule-e` and returns the
 * per-entry {@link ImportOutcome}. A validation failure surfaces as an
 * {@link ApiError} (400) whose `body.field` carries the structured dotted path
 * (`tax_year`, `entries`, `entries[i]`, `entries[i].lines[<line>]`,
 * `entries[i].new_property.<field>`) the form uses to place the message; a
 * not-owned property surfaces as a 404.
 */
export function importScheduleE(
  submission: ImportSubmission,
  signal?: AbortSignal,
): Promise<ImportOutcome> {
  return client.post<ImportOutcome>("/imports/schedule-e", {
    body: submission,
    signal,
  });
}

/**
 * Remove (undo) the imported set for one (Property, Tax_Year). Targets
 * `DELETE /imports/schedule-e/{propertyId}/{taxYear}` and returns the
 * {@link RemoveOutcome}. User-tracked transactions in that year are never
 * touched; a missing/not-owned property surfaces as a 404.
 */
export function removeScheduleEImport(
  propertyId: string,
  taxYear: number,
  signal?: AbortSignal,
): Promise<RemoveOutcome> {
  return client.delete<RemoveOutcome>(
    `/imports/schedule-e/${encodeURIComponent(propertyId)}/${encodeURIComponent(
      taxYear,
    )}`,
    { signal },
  );
}
