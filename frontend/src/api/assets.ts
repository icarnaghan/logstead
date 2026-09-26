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

/** A depreciable asset as returned by the backend. */
export interface DepreciableAsset {
  id: string;
  description: string;
  /** Two-decimal money string, e.g. "275000.00". */
  cost_basis: string;
  /** ISO date (YYYY-MM-DD) the asset was placed in service. */
  placed_in_service_date: string;
  recovery_period_years: number;
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
}

/** Body for updating an asset. */
export interface UpdateAssetInput {
  description: string;
  cost_basis: string;
  placed_in_service_date: string;
  recovery_period_years: number;
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
