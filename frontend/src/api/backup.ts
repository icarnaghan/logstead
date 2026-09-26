/**
 * Feature-scoped Backup / Restore / Clear API module.
 *
 * Wraps the shared {@link apiClient} with typed functions for the data-
 * portability feature (export a full backup, restore a document, clear all
 * data). It mirrors the `api/properties.ts` pattern: transport wiring lives in
 * one place behind a module-level {@link ApiClient} singleton, and tests inject
 * a fake-`fetch` client via {@link setBackupClient} so the real request/parse
 * path is exercised without hitting the network.
 *
 * The backend serializes dataclasses with snake_case field names and renders
 * every `Decimal` as a two-decimal string, so **all money and coordinate
 * fields below are typed `string`** and must never be coerced to `number`.
 * Errors surface as the shared {@link ApiError} (which carries `status` and a
 * parsed `body`); callers inspect `status` to map 400 validation to the right
 * UI message.
 */

import { ApiClient, apiClient, ApiError } from "../lib/apiClient";

// Re-export the error class as a value so callers can both catch it
// (`err instanceof ApiError`) and reference its type without importing the
// shared apiClient module directly. (Matches the sibling `properties.ts`.)
export { ApiError };

/** Per-tax-year usage days for a property, as embedded in a backup. */
export interface BackupUsageYear {
  tax_year: number;
  fair_rental_days: number;
  personal_use_days: number;
}

/** A single transaction row inside a backup. `amount` stays a string. */
export interface BackupTransaction {
  id: string;
  property_id: string;
  date: string;
  amount: string;
  type: "income" | "expense";
  category_id: string;
  schedule_e_line?: number | null;
  description?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/**
 * A depreciable asset inside a backup. `cost_basis` and
 * `recovery_period_years` are exact strings (never coerced to number).
 */
export interface BackupAsset {
  id: string;
  property_id: string;
  description: string;
  cost_basis: string;
  placed_in_service_date: string;
  recovery_period_years: string;
  created_at?: string | null;
  updated_at?: string | null;
}

/** One year's tax assessment inside a backup. Money fields are strings. */
export interface BackupTaxAssessment {
  year?: number | null;
  value?: string | null;
  land?: string | null;
  improvements?: string | null;
}

/** One year's property-tax total inside a backup. */
export interface BackupPropertyTax {
  year?: number | null;
  total?: string | null;
}

/** One entry in a property's sale history inside a backup. */
export interface BackupSaleEvent {
  date?: string | null;
  price?: string | null;
  event?: string | null;
}

/** HOA information inside a backup's property details. */
export interface BackupHoaDetails {
  fee?: string | null;
}

/** Ownership information inside a backup's property details. */
export interface BackupPropertyOwner {
  names?: string[] | null;
  type?: string | null;
  occupied?: boolean | null;
}

/** Structural feature flags/types inside a backup's property details. */
export interface BackupPropertyFeatures {
  architecture_type?: string | null;
  exterior_type?: string | null;
  foundation_type?: string | null;
  roof_type?: string | null;
  view_type?: string | null;
  heating?: boolean | null;
  heating_type?: string | null;
  cooling?: boolean | null;
  cooling_type?: string | null;
  garage?: boolean | null;
  garage_spaces?: number | null;
  garage_type?: string | null;
  pool?: boolean | null;
  pool_type?: string | null;
  fireplace?: boolean | null;
  fireplace_type?: string | null;
  floor_count?: number | null;
  room_count?: number | null;
  unit_count?: number | null;
}

/**
 * Permissive nested details subtree mirroring the backend's `PropertyDetails`.
 *
 * `details` is sparse, so every field is individually optional. Money and
 * coordinate fields (`latitude`, `longitude`, `bathrooms`, `lot_size`,
 * `last_sale_price`, …) are typed `string` to preserve exact precision.
 */
export interface BackupPropertyDetails {
  formatted_address?: string | null;
  address_line1?: string | null;
  address_line2?: string | null;
  city?: string | null;
  state?: string | null;
  zip_code?: string | null;
  county?: string | null;
  latitude?: string | null;
  longitude?: string | null;
  property_type?: string | null;
  bedrooms?: number | null;
  bathrooms?: string | null;
  living_area_sqft?: number | null;
  lot_size?: string | null;
  year_built?: number | null;
  assessor_id?: string | null;
  legal_description?: string | null;
  subdivision?: string | null;
  zoning?: string | null;
  last_sale_date?: string | null;
  last_sale_price?: string | null;
  features?: BackupPropertyFeatures | null;
  hoa?: BackupHoaDetails | null;
  owner?: BackupPropertyOwner | null;
  tax_assessments?: BackupTaxAssessment[] | null;
  property_taxes?: BackupPropertyTax[] | null;
  sale_history?: BackupSaleEvent[] | null;
}

/** A property and all of its child records inside a backup. */
export interface BackupProperty {
  id: string;
  name: string;
  address_text: string;
  property_type?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  details?: BackupPropertyDetails | null;
  note?: string | null;
  usage: BackupUsageYear[];
  transactions: BackupTransaction[];
  assets: BackupAsset[];
}

/** The versioned backup document exchanged with the backend. */
export interface BackupDocument {
  schema_version: string;
  exported_at: string;
  properties: BackupProperty[];
}

/** Counts returned after a successful restore. */
export interface RestoreSummary {
  properties: number;
  transactions: number;
  assets: number;
  usage_years: number;
}

/** Counts (and any S3 failures) returned after clearing all data. */
export interface ClearSummary {
  properties: number;
  transactions: number;
  assets: number;
  photos: number;
  receipts: number;
  failed_s3_keys: string[];
}

// The client is a module-level singleton so components share one instance, but
// tests can swap it for one backed by an injected fetch.
let client: ApiClient = apiClient;

/** Override the API client used by this module (tests inject a fake fetch). */
export function setBackupClient(next: ApiClient): void {
  client = next;
}

/** Reset back to the shared production client (call in test teardown). */
export function resetBackupClient(): void {
  client = apiClient;
}

/**
 * Fetch a full backup of the authenticated user's data (Requirement 1.12).
 *
 * Backend route: `GET /backup` → {@link BackupDocument}.
 */
export function fetchBackup(signal?: AbortSignal): Promise<BackupDocument> {
  return client.get<BackupDocument>("/backup", { signal });
}

/**
 * Restore a backup document, replacing all current data (Requirement 2.1).
 *
 * Backend route: `POST /backup/restore` with the document as the JSON body →
 * {@link RestoreSummary}. Server-side validation failures arrive as an
 * {@link ApiError} with status 400 and a field-specific message.
 */
export function restoreBackup(
  doc: BackupDocument,
  signal?: AbortSignal,
): Promise<RestoreSummary> {
  return client.post<RestoreSummary>("/backup/restore", { body: doc, signal });
}

/**
 * Clear all of the authenticated user's data (Requirement 7.1).
 *
 * Backend route: `POST /backup/clear` → {@link ClearSummary}.
 */
export function clearData(signal?: AbortSignal): Promise<ClearSummary> {
  return client.post<ClearSummary>("/backup/clear", { signal });
}
