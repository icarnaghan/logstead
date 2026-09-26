/**
 * Feature-scoped Properties API module.
 *
 * Wraps the shared {@link apiClient} with typed functions for the Properties
 * feature (list/create/get/update/delete, address autocomplete, and RentCast
 * enrichment). This keeps transport wiring in one place and lets components and
 * tests depend on small, well-typed functions rather than raw HTTP calls.
 *
 * The backend serializes dataclasses with snake_case field names and money as
 * two-decimal strings, so the types below mirror that shape exactly. Errors
 * surface as the shared {@link ApiError} (which carries `status` and a parsed
 * `body`); callers inspect `status` to map 400 validation (field-specific) and
 * 409 conflict (guarded delete) to the right UI message.
 *
 * By default this module uses the shared `apiClient`. Tests inject a custom
 * `ApiClient` (with a fake `fetch`) via {@link setPropertiesClient} so they can
 * exercise the real request/parse path without hitting the network.
 */

import { ApiClient, apiClient, ApiError } from "../lib/apiClient";

// Re-export the error class as a value so callers can both catch it
// (`err instanceof ApiError`) and reference its type without importing the
// shared apiClient module directly.
export { ApiError };

/**
 * Optional, RentCast-driven structure details nested under a property.
 *
 * Descriptive `*_type` fields carry a human-readable string; the paired boolean
 * flags (`heating`, `cooling`, `garage`, `pool`, `fireplace`) record presence.
 */
export interface PropertyFeatures {
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

/** A single year's tax assessment. Money fields arrive as strings. */
export interface TaxAssessment {
  year: number;
  value?: string | null;
  land?: string | null;
  improvements?: string | null;
}

/** A single year's property-tax total. */
export interface PropertyTax {
  year: number;
  total?: string | null;
}

/** A single entry in a property's sale history. */
export interface SaleEvent {
  date?: string | null;
  price?: string | null;
  event?: string | null;
}

/** HOA information for a property. */
export interface HoaDetails {
  fee?: string | null;
}

/** Ownership information for a property. */
export interface PropertyOwner {
  names?: string[] | null;
  type?: string | null;
  occupied?: boolean | null;
}

/**
 * Sparse property details. Every field is individually optional and is present
 * only when a provider (RentCast) supplied a value. Money/decimal fields arrive
 * as strings to preserve precision.
 */
export interface PropertyDetails {
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
  features?: PropertyFeatures | null;
  hoa?: HoaDetails | null;
  owner?: PropertyOwner | null;
  tax_assessments?: TaxAssessment[] | null;
  property_taxes?: PropertyTax[] | null;
  sale_history?: SaleEvent[] | null;
}

/** A rental property as returned by the API. */
export interface Property {
  id: string;
  user_id: string;
  name: string;
  address_text: string;
  property_type?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  /** Stored RentCast-driven details, present only when persisted. */
  details?: PropertyDetails | null;
}

/** Body for creating or updating a property. */
export interface PropertyInput {
  name: string;
  address_text: string;
  property_type?: string | null;
  /** Optional RentCast-driven details to persist at creation time. */
  details?: PropertyDetails | null;
}

/** A candidate address surfaced by the autocomplete provider. */
export interface AddressSuggestion {
  formatted_address: string;
  provider_place_id?: string | null;
}

/** Outcome of enriching a selected address via RentCast. */
export interface EnrichmentResult {
  status: "found" | "not_found" | "unavailable";
  details?: PropertyDetails | null;
  message?: string | null;
}

/** Per-tax-year usage days for a property. */
export interface PropertyUsageYear {
  property_id: string;
  tax_year: number;
  fair_rental_days: number;
  personal_use_days: number;
}

// The client is a module-level singleton so components share one instance, but
// tests can swap it for one backed by an injected fetch.
let client: ApiClient = apiClient;

/** Override the API client used by this module (tests inject a fake fetch). */
export function setPropertiesClient(next: ApiClient): void {
  client = next;
}

/** Reset back to the shared production client (call in test teardown). */
export function resetPropertiesClient(): void {
  client = apiClient;
}

/** List every property owned by the authenticated user (Requirement 2.3). */
export function listProperties(signal?: AbortSignal): Promise<Property[]> {
  return client.get<Property[]>("/properties", { signal });
}

/** Create a property; never blocked by enrichment (Requirements 2.1, 3.7). */
export function createProperty(
  input: PropertyInput,
  signal?: AbortSignal,
): Promise<Property> {
  return client.post<Property>("/properties", { body: input, signal });
}

/** Fetch one property (Requirement 2.9). */
export function getProperty(id: string, signal?: AbortSignal): Promise<Property> {
  return client.get<Property>(`/properties/${encodeURIComponent(id)}`, { signal });
}

/** Update an existing property (Requirement 2.4). */
export function updateProperty(
  id: string,
  input: PropertyInput,
  signal?: AbortSignal,
): Promise<Property> {
  return client.put<Property>(`/properties/${encodeURIComponent(id)}`, {
    body: input,
    signal,
  });
}

/**
 * Delete a property. The backend guards deletion against associated
 * transactions/assets and returns 409 when any exist (Requirements 2.6, 2.7);
 * callers catch the {@link ApiError} and surface its message.
 */
export function deleteProperty(id: string, signal?: AbortSignal): Promise<void> {
  return client.delete<void>(`/properties/${encodeURIComponent(id)}`, { signal });
}

/** Fetch address suggestions for partial text (Requirement 3.1). */
export function suggestAddresses(
  q: string,
  signal?: AbortSignal,
): Promise<AddressSuggestion[]> {
  return client.get<AddressSuggestion[]>("/addresses", {
    query: { q },
    signal,
  });
}

/**
 * Fetch the secondary (unit) addresses for a selected building (Requirement 3.1).
 *
 * Autocomplete only returns the base building; the individual units come from a
 * second server-side geocode lookup. Returns an empty list when the building
 * has no units (or the lookup fails), so the caller simply shows no unit picker.
 */
export function fetchUnitAddresses(
  address: string,
  signal?: AbortSignal,
): Promise<AddressSuggestion[]> {
  return client.get<AddressSuggestion[]>("/addresses/units", {
    query: { address },
    signal,
  });
}

/** Enrich a selected address into editable details (Requirements 3.2-3.6). */
export function enrichAddress(
  address: string,
  signal?: AbortSignal,
): Promise<EnrichmentResult> {
  return client.post<EnrichmentResult>("/properties/enrich", {
    body: { address },
    signal,
  });
}

/**
 * Fetch the free-text note stored for a property.
 *
 * Backend route: `GET /properties/{propertyId}/notes` → `{ text: string }`.
 * Returns just the note text (an empty string when no note has been saved).
 */
export function getPropertyNote(
  propertyId: string,
  signal?: AbortSignal,
): Promise<string> {
  return client
    .get<{ text: string }>(
      `/properties/${encodeURIComponent(propertyId)}/notes`,
      { signal },
    )
    .then((body) => body.text);
}

/**
 * Persist the free-text note for a property.
 *
 * Backend route: `PUT /properties/{propertyId}/notes` with body `{ text }` →
 * `{ text: string }`. Returns the saved note text.
 */
export function setPropertyNote(
  propertyId: string,
  text: string,
  signal?: AbortSignal,
): Promise<string> {
  return client
    .put<{ text: string }>(
      `/properties/${encodeURIComponent(propertyId)}/notes`,
      { body: { text }, signal },
    )
    .then((body) => body.text);
}

/** Set fair-rental / personal-use days for a tax year (Requirement 2.8). */
export function setUsageDays(
  propertyId: string,
  taxYear: number,
  fairRentalDays: number,
  personalUseDays: number,
  signal?: AbortSignal,
): Promise<PropertyUsageYear> {
  return client.put<PropertyUsageYear>(
    `/properties/${encodeURIComponent(propertyId)}/usage`,
    {
      body: {
        tax_year: taxYear,
        fair_rental_days: fairRentalDays,
        personal_use_days: personalUseDays,
      },
      signal,
    },
  );
}
