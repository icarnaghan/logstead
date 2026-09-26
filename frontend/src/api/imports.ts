/**
 * Expense-import API module.
 *
 * Wraps the shared {@link apiClient} with typed helpers for the expense-summary
 * import flow (Requirement 6):
 *
 *  - `createImport`  → `POST /imports`               start an import session
 *  - `getImport`     → `GET  /imports/{id}`          read the session status
 *  - `listDrafts`    → `GET  /imports/{id}/drafts`   list parsed draft transactions
 *  - `updateDraft`   → `PUT  /imports/{id}/drafts/{draftId}`  edit/complete a draft
 *  - `removeDraft`   → `DELETE /imports/{id}/drafts/{draftId}`  drop a draft
 *  - `confirmImport` → `POST /imports/{id}/confirm`  turn complete drafts into transactions
 *
 * The module is transport-only: it holds no UI state. Money values are strings
 * throughout (matching the backend contract). A `fileToBase64` helper reads a
 * `File` into a base64 string for the `pdf_base64` upload path; its reader is
 * injectable so it can be unit tested without a real browser `FileReader`.
 */

import { apiClient, type ApiClient } from "../lib/apiClient";

/** Lifecycle status of an import session. */
export type ImportStatus = "parsing" | "review" | "confirmed" | "failed";

/** A transaction is either income or an expense. */
export type TransactionType = "income" | "expense";

/** An import session returned by the backend. */
export interface ImportSession {
  id: string;
  property_id: string;
  tax_year: number;
  status: ImportStatus;
}

/**
 * A provisional, uncommitted transaction parsed from the expense summary.
 *
 * `missing_fields` lists the field names (e.g. `"date"`, `"amount"`,
 * `"category_id"`) that must be completed before the draft can be confirmed
 * (Requirement 6.9). Money is a string.
 */
export interface DraftTransaction {
  id: string;
  date: string | null;
  amount: string | null;
  description: string | null;
  type: TransactionType | null;
  category_id: string | null;
  missing_fields: string[];
}

/** A Schedule E category from `GET /categories`. */
export interface Category {
  id: string;
  kind: "income" | "expense";
  label: string;
  schedule_e_line: number;
  /** Line 19 ("Other") requires a description. */
  requires_description: boolean;
}

/** A draft that failed Requirement 5 validation on confirm. */
export interface RejectedDraft {
  draft_id: string;
  message: string;
  field: string;
}

/** The outcome of confirming an import session (Requirements 6.10, 6.11). */
export interface ConfirmOutcome {
  created_ids: string[];
  rejected: RejectedDraft[];
  converted_count: number;
  remaining_incomplete: number;
  session: ImportSession;
}

/** Editable draft fields sent to `updateDraft`. All optional. */
export interface DraftChanges {
  date?: string | null;
  amount?: string | null;
  description?: string | null;
  type?: TransactionType | null;
  category_id?: string | null;
}

/**
 * The body for `createImport`. Exactly one of `pdfBase64` / `pdfS3Key` is used;
 * the UI uploads via the base64 path.
 */
export interface CreateImportFile {
  pdfBase64?: string;
  pdfS3Key?: string;
  contentType: string;
}

/**
 * Start an import: upload an expense-summary PDF for a property + tax year.
 *
 * Returns the created {@link ImportSession}. A parse failure or unavailable
 * parser surfaces as an `ApiError` (503) whose message the UI displays with a
 * manual-entry suggestion; a non-PDF surfaces as a 400 with `field="file"`.
 */
export function createImport(
  propertyId: string,
  taxYear: number,
  file: CreateImportFile,
  client: ApiClient = apiClient,
): Promise<ImportSession> {
  const body: Record<string, unknown> = {
    property_id: propertyId,
    tax_year: taxYear,
    content_type: file.contentType,
  };
  if (file.pdfBase64 !== undefined) body.pdf_base64 = file.pdfBase64;
  if (file.pdfS3Key !== undefined) body.pdf_s3_key = file.pdfS3Key;
  return client.post<ImportSession>("/imports", { body });
}

/** Read an import session's current status. */
export function getImport(
  sessionId: string,
  client: ApiClient = apiClient,
): Promise<ImportSession> {
  return client.get<ImportSession>(`/imports/${sessionId}`);
}

/** List the draft transactions parsed for an import session. */
export function listDrafts(
  sessionId: string,
  client: ApiClient = apiClient,
): Promise<DraftTransaction[]> {
  return client.get<DraftTransaction[]>(`/imports/${sessionId}/drafts`);
}

/**
 * Edit/complete a draft. Returns the updated draft with recomputed
 * `missing_fields` (Requirements 6.7, 6.9).
 */
export function updateDraft(
  sessionId: string,
  draftId: string,
  changes: DraftChanges,
  client: ApiClient = apiClient,
): Promise<DraftTransaction> {
  return client.put<DraftTransaction>(
    `/imports/${sessionId}/drafts/${draftId}`,
    { body: changes },
  );
}

/** Remove a draft before confirming (Requirement 6.8). */
export function removeDraft(
  sessionId: string,
  draftId: string,
  client: ApiClient = apiClient,
): Promise<void> {
  return client.delete<void>(`/imports/${sessionId}/drafts/${draftId}`);
}

/**
 * Confirm the session: complete drafts become transactions; incomplete/invalid
 * ones are retained/rejected (Requirements 6.10, 6.11).
 */
export function confirmImport(
  sessionId: string,
  client: ApiClient = apiClient,
): Promise<ConfirmOutcome> {
  return client.post<ConfirmOutcome>(`/imports/${sessionId}/confirm`, {});
}

/** List the seeded Schedule E categories used to complete drafts. */
export function listCategories(
  client: ApiClient = apiClient,
): Promise<Category[]> {
  return client.get<Category[]>("/categories");
}

/**
 * Minimal shape of the browser `FileReader` we rely on. Declared locally so the
 * helper can be exercised with a fake reader in tests (no real DOM needed).
 */
export interface Base64Reader {
  readAsDataURL(file: Blob): void;
  onload: (() => void) | null;
  onerror: (() => void) | null;
  result: string | ArrayBuffer | null;
  error?: unknown;
}

/**
 * Read a `File` into a base64 string (without the `data:...;base64,` prefix)
 * for the `pdf_base64` upload path.
 *
 * The `FileReader` factory is injectable so this is testable without a browser
 * environment. In the app it defaults to the global `FileReader`.
 */
export function fileToBase64(
  file: Blob,
  makeReader: () => Base64Reader = () => new FileReader() as Base64Reader,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = makeReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("Failed to read file as a data URL"));
        return;
      }
      // Strip the "data:<mime>;base64," prefix, leaving only the payload.
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => {
      reject(reader.error ?? new Error("Failed to read file"));
    };
    reader.readAsDataURL(file);
  });
}
