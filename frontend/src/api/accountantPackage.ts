/**
 * Accountant package API module.
 *
 * Typed wrapper over the shared {@link apiClient} for the asynchronous
 * Accountant package routes under `/accountant-packages`. The wire carries no
 * money; `size_bytes` is an integer byte count.
 */

import { apiClient, type ApiClient } from "../lib/apiClient";

/** Lifecycle status of a package job. */
export type PackageStatus = "queued" | "running" | "complete" | "failed";

/** The wire view of one package job. */
export interface PackageJobView {
  readonly id: string;
  readonly status: PackageStatus;
  readonly tax_year: number;
  readonly property_ids: string[];
  readonly created_at: string;
  readonly finished_at: string | null;
  /** Failure text without internal detail; null otherwise. */
  readonly message: string | null;
  readonly size_bytes: number | null;
  readonly sha256: string | null;
  readonly file_count: number | null;
  readonly receipt_count: number | null;
  readonly skipped_receipt_count: number | null;
  /** Fresh presigned link; null unless the status is `complete`. */
  readonly download_url: string | null;
  readonly download_expires_in_seconds: number | null;
}

/** Response of `GET /accountant-packages`: newest first, at most 10. */
export interface PackageJobList {
  readonly jobs: PackageJobView[];
}

const BASE_PATH = "/accountant-packages";

function jobPath(jobId: string): string {
  return `${BASE_PATH}/${encodeURIComponent(jobId)}`;
}

/** The Accountant package API surface, with an injectable client for tests. */
export class AccountantPackageApi {
  private readonly client: ApiClient;

  constructor(client: ApiClient = apiClient) {
    this.client = client;
  }

  /** Start a package job. Omit `propertyIds` to include every property. */
  createPackage(
    taxYear: number,
    propertyIds?: string[],
    signal?: AbortSignal,
  ): Promise<PackageJobView> {
    const body: { tax_year: number; property_ids?: string[] } = {
      tax_year: taxYear,
    };
    if (propertyIds !== undefined) body.property_ids = propertyIds;
    return this.client.post<PackageJobView>(BASE_PATH, { body, signal });
  }

  /** The user's recent package jobs, newest first. */
  listPackages(signal?: AbortSignal): Promise<PackageJobList> {
    return this.client.get<PackageJobList>(BASE_PATH, { signal });
  }

  /** One package job, with a fresh download link when complete. */
  getPackage(jobId: string, signal?: AbortSignal): Promise<PackageJobView> {
    return this.client.get<PackageJobView>(jobPath(jobId), { signal });
  }

  /** Delete a finished package job and its ZIP. */
  deletePackage(jobId: string, signal?: AbortSignal): Promise<void> {
    return this.client.delete<void>(jobPath(jobId), { signal });
  }
}

/** Shared instance wired to the app's singleton API client. */
export const accountantPackageApi = new AccountantPackageApi();
