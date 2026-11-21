/**
 * Feature-scoped Business entities API module.
 *
 * Wraps the shared {@link apiClient} with typed functions for the Business
 * entities feature (list/create/get/update/delete, per-business document
 * uploads via pre-signed S3 URLs, and the property↔business link). This keeps
 * transport wiring in one place and lets components and tests depend on small,
 * well-typed functions rather than raw HTTP calls.
 *
 * The backend serializes dataclasses with snake_case field names, so the types
 * below mirror that shape exactly. Identifiers are always strings and are never
 * coerced to numbers; this feature introduces no money fields. Errors surface
 * as the shared {@link ApiError} (which carries `status` and a parsed `body`);
 * callers inspect `status` to map 400 validation (field-specific), 404
 * not-found, and 409 conflict (guarded delete) to the right UI message.
 *
 * By default this module uses the shared `apiClient`. Tests inject a custom
 * `ApiClient` (with a fake `fetch`) via {@link setBusinessesClient} so they can
 * exercise the real request/parse path without hitting the network. The
 * pre-signed-upload PUT reuses the helper exported by `api/photos.ts`.
 */

import { ApiClient, apiClient, ApiError } from "../lib/apiClient";
import { uploadToPresignedUrl } from "./photos";

// Re-export the error class as a value so callers can both catch it
// (`err instanceof ApiError`) and reference its type without importing the
// shared apiClient module directly.
export { ApiError };

// Re-export the pre-signed upload helper so the Business documents UI can PUT
// bytes to S3 without importing the photos module directly (same flow).
export { uploadToPresignedUrl };

/**
 * The fixed, stable set of business entity types stored verbatim on the wire.
 * The UI renders human labels; storage uses these exact values.
 */
export const ENTITY_TYPES = [
  "llc",
  "sole_proprietorship",
  "partnership",
  "s_corporation",
  "c_corporation",
  "individual_other",
] as const;

/** A single business entity_type value. */
export type EntityType = (typeof ENTITY_TYPES)[number];

/**
 * A business entity as returned by the API. Field names mirror the backend
 * `Business` dataclass (snake_case on the wire); every field is a string.
 * Optional fields are omitted when unset.
 */
export interface Business {
  id: string;
  user_id: string;
  legal_name: string;
  entity_type: string;
  /** Free text, stored exactly as entered (never an SSN). */
  ein?: string | null;
  /** Two-letter uppercase US state code, e.g. "CA". */
  formation_state?: string | null;
  /** ISO YYYY-MM-DD date string. */
  formation_date?: string | null;
  business_address?: string | null;
  /** MM-DD string; defaults to "12-31" when omitted on create. */
  tax_year_end: string;
  note?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/**
 * Body for creating or updating a business. `legal_name` and `entity_type` are
 * required; everything else is optional (omitted when blank). `tax_year_end`
 * defaults to "12-31" server-side when omitted.
 */
export interface BusinessInput {
  legal_name: string;
  entity_type: string;
  ein?: string | null;
  formation_state?: string | null;
  formation_date?: string | null;
  business_address?: string | null;
  tax_year_end?: string | null;
  note?: string | null;
}

/** A reference to a property linked to a business, resolved to its name. */
export interface LinkedPropertyRef {
  id: string;
  name: string;
}

/**
 * The `GET /businesses/{id}` response. In addition to the business fields, the
 * backend carries the names of the properties linked to this business so the UI
 * never has to show a raw identifier.
 */
export interface BusinessWithLinks extends Business {
  linked_properties?: LinkedPropertyRef[];
}

/**
 * Business document metadata as returned by the backend. Field names mirror the
 * backend `BusinessDocument` dataclass (snake_case on the wire).
 */
export interface BusinessDocument {
  id: string;
  business_id: string;
  s3_key: string;
  content_type: string;
  original_filename: string;
  uploaded_at?: string | null;
}

/** Response body of `POST /businesses/{businessId}/documents`. */
export interface PresignedDocumentUpload {
  /** Pre-signed S3 PUT URL the browser uploads the bytes to. */
  upload_url: string;
  document: BusinessDocument;
}

/** An element of `GET /businesses/{businessId}/documents`. */
export interface BusinessDocumentWithUrl {
  document: BusinessDocument;
  /** Pre-signed S3 GET URL used to download the document. */
  download_url: string;
}

// The client is a module-level singleton so components share one instance, but
// tests can swap it for one backed by an injected fetch.
let client: ApiClient = apiClient;

/** Override the API client used by this module (tests inject a fake fetch). */
export function setBusinessesClient(next: ApiClient): void {
  client = next;
}

/** Reset back to the shared production client (call in test teardown). */
export function resetBusinessesClient(): void {
  client = apiClient;
}

/** List every business owned by the authenticated user (Requirement 11.2). */
export function listBusinesses(signal?: AbortSignal): Promise<Business[]> {
  return client.get<Business[]>("/businesses", { signal });
}

/** Create a business (Requirements 1.1-1.6). */
export function createBusiness(
  input: BusinessInput,
  signal?: AbortSignal,
): Promise<Business> {
  return client.post<Business>("/businesses", { body: input, signal });
}

/**
 * Fetch one business, including the names of its linked properties
 * (Requirements 3.2, 10.2).
 */
export function getBusiness(
  id: string,
  signal?: AbortSignal,
): Promise<BusinessWithLinks> {
  return client.get<BusinessWithLinks>(
    `/businesses/${encodeURIComponent(id)}`,
    { signal },
  );
}

/** Update an existing business (Requirement 4). */
export function updateBusiness(
  id: string,
  input: BusinessInput,
  signal?: AbortSignal,
): Promise<Business> {
  return client.put<Business>(`/businesses/${encodeURIComponent(id)}`, {
    body: input,
    signal,
  });
}

/**
 * Delete a business. The backend guards deletion against linked properties and
 * returns 409 when any exist (Requirement 5.2); callers catch the
 * {@link ApiError} and surface its message.
 */
export function deleteBusiness(id: string, signal?: AbortSignal): Promise<void> {
  return client.delete<void>(`/businesses/${encodeURIComponent(id)}`, { signal });
}

/** List a business's documents with their download URLs (Requirement 7). */
export function listDocuments(
  businessId: string,
  signal?: AbortSignal,
): Promise<BusinessDocumentWithUrl[]> {
  return client.get<BusinessDocumentWithUrl[]>(
    `/businesses/${encodeURIComponent(businessId)}/documents`,
    { signal },
  );
}

/**
 * Request a pre-signed upload URL and record the document metadata
 * (Requirement 6). The backend rejects disallowed content types; the UI also
 * validates client-side before calling this. Follow up by PUTting the bytes to
 * `upload_url` with {@link uploadToPresignedUrl}.
 */
export function requestDocumentUpload(
  businessId: string,
  filename: string,
  contentType: string,
  signal?: AbortSignal,
): Promise<PresignedDocumentUpload> {
  return client.post<PresignedDocumentUpload>(
    `/businesses/${encodeURIComponent(businessId)}/documents`,
    { body: { filename, content_type: contentType }, signal },
  );
}

/** Delete a business document and its S3 object (Requirement 8). */
export function deleteDocument(
  businessId: string,
  documentId: string,
  signal?: AbortSignal,
): Promise<void> {
  return client.delete<void>(
    `/businesses/${encodeURIComponent(businessId)}/documents/${encodeURIComponent(
      documentId,
    )}`,
    { signal },
  );
}

/**
 * Set, change, or clear a property's owning business (Requirement 9). Pass a
 * `businessId` to link (set/change) or `null` to clear. Routes to
 * `PUT /properties/{propertyId}/business` with body `{ business_id }`.
 */
export function setPropertyBusiness(
  propertyId: string,
  businessId: string | null,
  signal?: AbortSignal,
): Promise<void> {
  return client.put<void>(
    `/properties/${encodeURIComponent(propertyId)}/business`,
    { body: { business_id: businessId }, signal },
  );
}
