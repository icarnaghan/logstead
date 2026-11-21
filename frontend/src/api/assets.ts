/**
 * Depreciable-assets API module.
 *
 * Wraps the shared {@link apiClient} with typed helpers for the per-property
 * depreciable-asset endpoints (Requirements 8, 9). Money values are exchanged
 * as two-decimal strings, matching the backend's `decimal.Decimal`-as-string
 * convention; this module never coerces them to `number` so no precision is
 * lost in the UI layer.
 *
 * Backend routes (task 16.1):
 *  - GET    /properties/{propertyId}/assets
 *  - POST   /properties/{propertyId}/assets
 *  - GET    /properties/{propertyId}/assets/{assetId}
 *  - PUT    /properties/{propertyId}/assets/{assetId}
 *  - DELETE /properties/{propertyId}/assets/{assetId}
 *  - GET    /properties/{propertyId}/assets/{assetId}/schedule
 */

import { apiClient, type ApiClient } from "../lib/apiClient";

/** The default recovery period (years) for residential rental building assets. */
export const DEFAULT_RECOVERY_PERIOD_YEARS = 27.5;

/**
 * Per-year depreciation overrides (Requirement 1.1, 1.4): a JSON object keyed by
 * tax-year string (the object-key form the backend emits and accepts) whose
 * values are two-decimal money strings, e.g. `{ "2010": "1952.00" }`.
 *
 * Values are always strings, never numbers — this preserves the "no float"
 * money contract shared across this module. An absent or empty map means the
 * asset has no overrides.
 */
export type DepreciationOverrides = Record<string, string>;

/** A depreciable asset as returned by the backend. */
export interface DepreciableAsset {
  id: string;
  description: string;
  /** Two-decimal money string, e.g. "275000.00". */
  cost_basis: string;
  /** ISO date (YYYY-MM-DD) the asset was placed in service. */
  placed_in_service_date: string;
  recovery_period_years: number;
  /** Optional per-year overrides; absent/empty == no overrides. */
  depreciation_overrides?: DepreciationOverrides;
  created_at: string;
  updated_at: string;
}

/** Body for creating an asset. `recovery_period_years` is optional (server default). */
export interface CreateAssetInput {
  description: string;
  /** Two-decimal money string; the backend rejects values <= 0. */
  cost_basis: string;
  placed_in_service_date: string;
  recovery_period_years?: number;
  /** Optional per-year overrides; absent/empty == no overrides. */
  depreciation_overrides?: DepreciationOverrides;
}

/** Body for updating an asset. */
export interface UpdateAssetInput {
  description: string;
  cost_basis: string;
  placed_in_service_date: string;
  recovery_period_years: number;
  /** Optional per-year overrides; absent/empty == no overrides. */
  depreciation_overrides?: DepreciationOverrides;
}

/** One row of a computed straight-line / mid-month depreciation schedule. */
export interface ScheduleRow {
  tax_year: number;
  /** Two-decimal money string for that year's depreciation. */
  amount: string;
  /** Two-decimal money string for the basis remaining after that year. */
  remaining_basis: string;
  method: string;
  convention: string;
}

function assetsPath(propertyId: string): string {
  return `/properties/${encodeURIComponent(propertyId)}/assets`;
}

function assetPath(propertyId: string, assetId: string): string {
  return `${assetsPath(propertyId)}/${encodeURIComponent(assetId)}`;
}

/** Lists all depreciable assets for a property (Requirement 8.7). */
export function listAssets(
  propertyId: string,
  client: ApiClient = apiClient,
): Promise<DepreciableAsset[]> {
  return client.get<DepreciableAsset[]>(assetsPath(propertyId));
}

/** Creates a depreciable asset for a property (Requirement 8.1). */
export function createAsset(
  propertyId: string,
  input: CreateAssetInput,
  client: ApiClient = apiClient,
): Promise<DepreciableAsset> {
  return client.post<DepreciableAsset>(assetsPath(propertyId), { body: input });
}

/** Fetches a single depreciable asset. */
export function getAsset(
  propertyId: string,
  assetId: string,
  client: ApiClient = apiClient,
): Promise<DepreciableAsset> {
  return client.get<DepreciableAsset>(assetPath(propertyId, assetId));
}

/** Updates a depreciable asset and triggers schedule recomputation (Requirement 8.5). */
export function updateAsset(
  propertyId: string,
  assetId: string,
  input: UpdateAssetInput,
  client: ApiClient = apiClient,
): Promise<DepreciableAsset> {
  return client.put<DepreciableAsset>(assetPath(propertyId, assetId), {
    body: input,
  });
}

/** Deletes a depreciable asset and its schedule (Requirement 8.6). */
export function deleteAsset(
  propertyId: string,
  assetId: string,
  client: ApiClient = apiClient,
): Promise<void> {
  return client.delete<void>(assetPath(propertyId, assetId));
}

/** Fetches an asset's year-by-year depreciation schedule (Requirement 9.4). */
export function getSchedule(
  propertyId: string,
  assetId: string,
  client: ApiClient = apiClient,
): Promise<ScheduleRow[]> {
  return client.get<ScheduleRow[]>(
    `${assetPath(propertyId, assetId)}/schedule`,
  );
}

/**
 * One property's depreciable-asset count and depreciation total for a tax year,
 * as returned by the dashboard asset-summary aggregation endpoint
 * (Requirement 3). `depreciation_total` is the authoritative Schedule E Line 18
 * figure for that property and year (Requirement 6.1).
 */
export interface PropertyAssetSummary {
  readonly property_id: string;
  readonly property_name: string;
  /** Count of {@link DepreciableAsset} records for the property. */
  readonly asset_count: number;
  /** Fixed two-decimal money string, e.g. "1250.00"; never a number. */
  readonly depreciation_total: string;
}

/**
 * The read-only per-property depreciable-assets summary for the authenticated
 * user and a tax year (Requirements 3, 4). One entry per owned property.
 */
export interface AssetSummary {
  /** The tax year every depreciation total is derived for. */
  readonly tax_year: number;
  /** Per-property summaries, in the order the property service lists them. */
  readonly properties: readonly PropertyAssetSummary[];
}

/**
 * Fetches the dashboard depreciable-assets summary for a tax year via a single
 * aggregation read (Requirement 4.1), rather than one `listAssets` call per
 * property. Money stays a two-decimal string; it is never coerced to `number`
 * (Requirement 3.5).
 */
export function getAssetSummary(
  taxYear: number,
  client: ApiClient = apiClient,
): Promise<AssetSummary> {
  return client.get<AssetSummary>("/dashboard/assets", {
    query: { taxYear },
  });
}
