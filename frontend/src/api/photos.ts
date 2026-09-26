/**
 * Property photos API module (feature-scoped).
 *
 * Wraps the shared {@link apiClient} with the three photo endpoints exposed by
 * the backend (task 16.1) and a small helper that PUTs the raw bytes to the
 * pre-signed S3 URL the backend returns:
 *
 *   - `POST   /properties/{propertyId}/photos`            → request a pre-signed upload
 *   - `GET    /properties/{propertyId}/photos`            → list photos with display URLs
 *   - `DELETE /properties/{propertyId}/photos/{photoId}`  → delete a photo
 *
 * The wire shapes use the backend's snake_case dataclass field names. This file
 * is intentionally transport-only (no React, no business rules) so it can be
 * unit tested by injecting an `apiClient` and a `fetch` implementation.
 */

import { apiClient, type ApiClient } from "../lib/apiClient";

/**
 * Accepted image content types for property photo uploads (Requirement 4.2).
 *
 * Kept in sync with the backend allow-list (`ALLOWED_CONTENT_TYPES` in
 * `services/photo.py`). Client-side validation rejects anything outside this
 * set before a pre-signed URL is ever requested.
 */
export const ALLOWED_IMAGE_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/heic",
  "image/heif",
] as const;

export type AllowedImageType = (typeof ALLOWED_IMAGE_TYPES)[number];

/** Human-readable list of accepted types for validation messages. */
export const ALLOWED_IMAGE_TYPES_LABEL = "JPEG, PNG, WebP, HEIC, or HEIF";

/** True when `contentType` is one of the accepted image types. */
export function isAllowedImageType(contentType: string): boolean {
  return (ALLOWED_IMAGE_TYPES as readonly string[]).includes(contentType);
}

/**
 * Photo metadata as returned by the backend. Field names mirror the backend
 * `PropertyPhoto` dataclass (snake_case on the wire).
 */
export interface PropertyPhoto {
  id: string;
  property_id: string;
  s3_key: string;
  content_type: string;
  original_filename: string;
  uploaded_at: string | null;
}

/** Response body of `POST /properties/{propertyId}/photos`. */
export interface PresignedUpload {
  /** Pre-signed S3 PUT URL the browser uploads the bytes to. */
  upload_url: string;
  photo: PropertyPhoto;
}

/** An element of `GET /properties/{propertyId}/photos`. */
export interface PhotoWithUrl {
  photo: PropertyPhoto;
  /** Pre-signed S3 GET URL used as the `<img src>` for display. */
  display_url: string;
}

/**
 * Feature API surface. The default export is bound to the shared `apiClient`
 * and global `fetch`; tests construct their own instance with injected doubles.
 */
export class PhotosApi {
  private readonly client: Pick<ApiClient, "get" | "post" | "delete">;
  private readonly fetchImpl: typeof fetch;

  constructor(
    client: Pick<ApiClient, "get" | "post" | "delete"> = apiClient,
    fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis),
  ) {
    this.client = client;
    this.fetchImpl = fetchImpl;
  }

  /** List all photos for a property with their display URLs (Requirement 4.3). */
  listPhotos(propertyId: string): Promise<PhotoWithUrl[]> {
    return this.client.get<PhotoWithUrl[]>(
      `/properties/${encodeURIComponent(propertyId)}/photos`,
    );
  }

  /**
   * Request a pre-signed upload URL and record the photo metadata (Requirement
   * 4.1). The backend rejects disallowed content types (Requirement 4.2); the
   * UI also validates client-side before calling this.
   */
  requestUpload(
    propertyId: string,
    filename: string,
    contentType: string,
  ): Promise<PresignedUpload> {
    return this.client.post<PresignedUpload>(
      `/properties/${encodeURIComponent(propertyId)}/photos`,
      { body: { filename, content_type: contentType } },
    );
  }

  /** Delete a photo and remove its association with the property (Requirement 4.4). */
  deletePhoto(propertyId: string, photoId: string): Promise<void> {
    return this.client.delete<void>(
      `/properties/${encodeURIComponent(propertyId)}/photos/${encodeURIComponent(
        photoId,
      )}`,
    );
  }

  /**
   * Upload the file bytes directly to S3 via the pre-signed PUT URL. The
   * `Content-Type` header must match what the URL was signed for.
   *
   * Throws if S3 responds with a non-2xx status.
   */
  async uploadToPresignedUrl(url: string, file: File): Promise<void> {
    const response = await this.fetchImpl(url, {
      method: "PUT",
      body: file,
      headers: { "Content-Type": file.type },
    });
    if (!response.ok) {
      throw new Error(
        `Photo upload to storage failed with status ${response.status}`,
      );
    }
  }
}

/** Shared instance wired to the app's `apiClient` and global `fetch`. */
export const photosApi = new PhotosApi();

// Convenience free functions bound to the shared instance, matching the task's
// requested API (`listPhotos`, `requestUpload`, `deletePhoto`, `uploadToPresignedUrl`).
export const listPhotos = (propertyId: string): Promise<PhotoWithUrl[]> =>
  photosApi.listPhotos(propertyId);

export const requestUpload = (
  propertyId: string,
  filename: string,
  contentType: string,
): Promise<PresignedUpload> =>
  photosApi.requestUpload(propertyId, filename, contentType);

export const deletePhoto = (
  propertyId: string,
  photoId: string,
): Promise<void> => photosApi.deletePhoto(propertyId, photoId);

export const uploadToPresignedUrl = (
  url: string,
  file: File,
  fetchImpl?: typeof fetch,
): Promise<void> =>
  fetchImpl
    ? new PhotosApi(apiClient, fetchImpl).uploadToPresignedUrl(url, file)
    : photosApi.uploadToPresignedUrl(url, file);
