/**
 * Transactions API module.
 *
 * Thin, typed wrapper over the shared {@link apiClient} for the per-property
 * transactions feature (Requirements 5.1–5.8, 7.3, 7.4). It covers:
 *  - the Schedule E category catalog (`GET /categories`),
 *  - transaction CRUD scoped to a property (`.../properties/{id}/transactions`),
 *  - receipt attachment via a pre-signed S3 URL (request URL → PUT bytes → list).
 *
 * Money is represented as fixed two-decimal **strings** end-to-end (never
 * floating point), matching the backend contract (Requirement 13.3). The
 * module is transport-only: it holds no UI state and accepts an injectable
 * client / fetch so it is easy to unit test without a network.
 */

import { apiClient, type ApiClient } from "../lib/apiClient";

/** income vs. expense — the two Schedule E transaction kinds (Requirement 5.1). */
export type TransactionType = "income" | "expense";

/**
 * A Schedule E category the user can assign to a transaction (Requirement 7.1,
 * 7.2). `requires_description` is true for the "Other" expense (Line 19) so the
 * UI can enforce a free-text description (Requirement 7.4).
 */
export interface Category {
  readonly id: string;
  readonly kind: TransactionType;
  readonly label: string;
  /** e.g. "3", "14", "19" — the Schedule E Part I line number. */
  readonly schedule_e_line: string;
  readonly requires_description: boolean;
}

/** A persisted transaction as returned by the API. */
export interface Transaction {
  readonly id: string;
  readonly property_id: string;
  /** ISO date (YYYY-MM-DD). */
  readonly date: string;
  /** Fixed two-decimal string, e.g. "1250.00". */
  readonly amount: string;
  readonly type: TransactionType;
  readonly category_id: string;
  readonly description?: string | null;
}

/** Request body for creating a transaction (Requirement 5.1). */
export interface TransactionInput {
  date: string;
  /** Money as a fixed two-decimal string. */
  amount: string;
  type: TransactionType;
  category_id: string;
  description?: string;
}

/** Fields that can change on an existing transaction (Requirement 5.6). */
export type TransactionChanges = Partial<TransactionInput>;

/** Receipt document metadata associated with a transaction (Requirement 5.8). */
export interface ReceiptDocument {
  readonly id: string;
  readonly filename: string;
  readonly content_type: string;
  /** Optional pre-signed download URL when the API supplies one. */
  readonly download_url?: string;
}

/** Response from requesting a receipt upload: a pre-signed PUT URL + metadata. */
export interface AttachReceiptResult {
  readonly upload_url: string;
  readonly document: ReceiptDocument;
}

/**
 * Server validation errors are HTTP 400 with a `field` naming the offending
 * input (Requirement 14.3). This shape lets the UI place the message next to
 * the right control.
 */
export interface ApiFieldError {
  readonly field?: string;
  readonly message?: string;
}

/** Extract a `{ field, message }` from an unknown ApiError body, if present. */
export function fieldErrorFrom(body: unknown): ApiFieldError | null {
  if (typeof body !== "object" || body === null) return null;
  const record = body as Record<string, unknown>;
  const field = typeof record.field === "string" ? record.field : undefined;
  const message =
    typeof record.message === "string" ? record.message : undefined;
  if (field === undefined && message === undefined) return null;
  return { field, message };
}

function transactionsPath(propertyId: string): string {
  return `/properties/${encodeURIComponent(propertyId)}/transactions`;
}

function transactionPath(propertyId: string, transactionId: string): string {
  return `${transactionsPath(propertyId)}/${encodeURIComponent(transactionId)}`;
}

function receiptsPath(propertyId: string, transactionId: string): string {
  return `${transactionPath(propertyId, transactionId)}/receipts`;
}

/**
 * The transactions API surface. Injectable {@link ApiClient} and `fetch` keep
 * it unit-testable; the default export wires the shared singletons.
 */
export class TransactionsApi {
  private readonly client: ApiClient;
  private readonly fetchImpl: typeof fetch;

  constructor(client: ApiClient = apiClient, fetchImpl?: typeof fetch) {
    this.client = client;
    this.fetchImpl = fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  /** The fixed Schedule E category catalog (Requirement 7.1, 7.2). */
  listCategories(signal?: AbortSignal): Promise<Category[]> {
    return this.client.get<Category[]>("/categories", { signal });
  }

  /**
   * Transactions for a property, date-descending (Requirement 5.4). Omitting
   * `taxYear` returns all years; supplying it restricts to that year
   * (Requirement 5.5).
   */
  listTransactions(
    propertyId: string,
    taxYear?: number,
    signal?: AbortSignal,
  ): Promise<Transaction[]> {
    return this.client.get<Transaction[]>(transactionsPath(propertyId), {
      query: taxYear === undefined ? undefined : { taxYear },
      signal,
    });
  }

  /** Create a transaction on a property (Requirement 5.1). */
  createTransaction(
    propertyId: string,
    input: TransactionInput,
    signal?: AbortSignal,
  ): Promise<Transaction> {
    return this.client.post<Transaction>(transactionsPath(propertyId), {
      body: input,
      signal,
    });
  }

  /** Fetch a single transaction. */
  getTransaction(
    propertyId: string,
    transactionId: string,
    signal?: AbortSignal,
  ): Promise<Transaction> {
    return this.client.get<Transaction>(
      transactionPath(propertyId, transactionId),
      { signal },
    );
  }

  /** Update an existing transaction (Requirement 5.6). */
  updateTransaction(
    propertyId: string,
    transactionId: string,
    changes: TransactionChanges,
    signal?: AbortSignal,
  ): Promise<Transaction> {
    return this.client.put<Transaction>(
      transactionPath(propertyId, transactionId),
      { body: changes, signal },
    );
  }

  /** Delete a transaction (Requirement 5.7). */
  deleteTransaction(
    propertyId: string,
    transactionId: string,
    signal?: AbortSignal,
  ): Promise<void> {
    return this.client.delete<void>(
      transactionPath(propertyId, transactionId),
      { signal },
    );
  }

  /**
   * Request a pre-signed upload for a receipt (Requirement 5.8). The caller
   * then PUTs the bytes to `upload_url` via {@link uploadToPresignedUrl}.
   */
  attachReceipt(
    propertyId: string,
    transactionId: string,
    filename: string,
    contentType: string,
    signal?: AbortSignal,
  ): Promise<AttachReceiptResult> {
    return this.client.post<AttachReceiptResult>(
      receiptsPath(propertyId, transactionId),
      { body: { filename, content_type: contentType }, signal },
    );
  }

  /**
   * PUT the raw file bytes to a pre-signed S3 URL. This bypasses the API
   * client because the URL is a direct S3 endpoint with its own auth baked
   * into the query string — no bearer token, no JSON envelope.
   */
  async uploadToPresignedUrl(
    uploadUrl: string,
    file: Blob,
    contentType?: string,
    signal?: AbortSignal,
  ): Promise<void> {
    const response = await this.fetchImpl(uploadUrl, {
      method: "PUT",
      headers: contentType ? { "Content-Type": contentType } : undefined,
      body: file,
      signal,
    });
    if (!response.ok) {
      throw new Error(
        `Receipt upload failed with status ${response.status}`,
      );
    }
  }

  /** List receipts attached to a transaction (Requirement 5.8). */
  listReceipts(
    propertyId: string,
    transactionId: string,
    signal?: AbortSignal,
  ): Promise<ReceiptDocument[]> {
    return this.client.get<ReceiptDocument[]>(
      receiptsPath(propertyId, transactionId),
      { signal },
    );
  }

  /** Delete a receipt document from a transaction. */
  deleteReceipt(
    propertyId: string,
    transactionId: string,
    documentId: string,
    signal?: AbortSignal,
  ): Promise<void> {
    return this.client.delete<void>(
      `${receiptsPath(propertyId, transactionId)}/${encodeURIComponent(documentId)}`,
      { signal },
    );
  }
}

/** Shared instance wired to the app's singleton API client. */
export const transactionsApi = new TransactionsApi();
