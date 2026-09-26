import { useCallback, useEffect, useRef, useState } from "react";
import {
  confirmImport as confirmImportApi,
  createImport as createImportApi,
  fileToBase64 as fileToBase64Api,
  listCategories as listCategoriesApi,
  listDrafts as listDraftsApi,
  removeDraft as removeDraftApi,
  updateDraft as updateDraftApi,
  type Category,
  type ConfirmOutcome,
  type CreateImportFile,
  type DraftChanges,
  type DraftTransaction,
} from "../../api/imports";
import { ApiError } from "../../lib/apiClient";
import { DraftRow } from "./DraftRow";

/**
 * The subset of the imports API this component depends on. Injected as a single
 * object so tests can supply fakes without touching the network (the app uses
 * the real, shared-`apiClient`-backed defaults).
 */
export interface ImportApi {
  createImport: (
    propertyId: string,
    taxYear: number,
    file: CreateImportFile,
  ) => Promise<{ id: string }>;
  listDrafts: (sessionId: string) => Promise<DraftTransaction[]>;
  updateDraft: (
    sessionId: string,
    draftId: string,
    changes: DraftChanges,
  ) => Promise<DraftTransaction>;
  removeDraft: (sessionId: string, draftId: string) => Promise<void>;
  confirmImport: (sessionId: string) => Promise<ConfirmOutcome>;
  listCategories: () => Promise<Category[]>;
  fileToBase64: (file: Blob) => Promise<string>;
}

const defaultApi: ImportApi = {
  createImport: (propertyId, taxYear, file) =>
    createImportApi(propertyId, taxYear, file),
  listDrafts: (sessionId) => listDraftsApi(sessionId),
  updateDraft: (sessionId, draftId, changes) =>
    updateDraftApi(sessionId, draftId, changes),
  removeDraft: (sessionId, draftId) => removeDraftApi(sessionId, draftId),
  confirmImport: (sessionId) => confirmImportApi(sessionId),
  listCategories: () => listCategoriesApi(),
  fileToBase64: (file) => fileToBase64Api(file),
};

interface ImportReviewProps {
  /** The property this import is associated with. */
  propertyId: string;
  /** The tax year this import is associated with. */
  taxYear: number;
  /** Injectable API, primarily for tests. Defaults to the real client. */
  api?: Partial<ImportApi>;
}

const PDF_TYPE = "application/pdf";

function errorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return fallback;
}

/**
 * Self-contained expense-summary import + review UI (Requirement 6).
 *
 * Flow:
 *  1. Upload a PDF. Non-PDF files are rejected client-side with an accessible
 *     message (Requirement 6.2). A parse failure/unavailable parser from the
 *     server shows the returned message and suggests manual entry
 *     (Requirement 6.12).
 *  2. Parsed drafts are listed with their missing-field flags for review
 *     (Requirements 6.5, 6.9); each can be edited to completion or removed
 *     (Requirements 6.7, 6.8). No transactions exist yet (Requirement 6.6).
 *  3. Confirm turns complete drafts into transactions and reports how many were
 *     converted and which remain incomplete/rejected (Requirements 6.10, 6.11).
 *
 * Takes `propertyId` + `taxYear` props so it can be mounted anywhere (e.g. from
 * the transactions area) without router changes.
 */
export function ImportReview({ propertyId, taxYear, api }: ImportReviewProps) {
  const client: ImportApi = { ...defaultApi, ...api };
  // Keep the resolved API stable across renders so effects don't re-run.
  const clientRef = useRef(client);
  clientRef.current = client;

  const [categories, setCategories] = useState<Category[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<DraftTransaction[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [outcome, setOutcome] = useState<ConfirmOutcome | null>(null);

  useEffect(() => {
    let cancelled = false;
    clientRef.current
      .listCategories()
      .then((cats) => {
        if (!cancelled) setCategories(cats);
      })
      .catch(() => {
        // A category load failure is non-fatal: the user can still see drafts,
        // they just won't have the category picker populated.
        if (!cancelled) setCategories([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleFileChange = useCallback(
    async (file: File | null) => {
      setFileError(null);
      setUploadError(null);
      setOutcome(null);
      if (!file) return;

      // Client-side non-PDF rejection (Requirement 6.2).
      const isPdf =
        file.type === PDF_TYPE || file.name.toLowerCase().endsWith(".pdf");
      if (!isPdf) {
        setFileError("A PDF file is required.");
        return;
      }

      setUploading(true);
      try {
        const pdfBase64 = await clientRef.current.fileToBase64(file);
        const session = await clientRef.current.createImport(
          propertyId,
          taxYear,
          { pdfBase64, contentType: PDF_TYPE },
        );
        setSessionId(session.id);
        const parsed = await clientRef.current.listDrafts(session.id);
        setDrafts(parsed);
        if (parsed.length === 0) {
          // Parsed, but no line items (Requirement 6.12).
          setUploadError(
            "No transactions could be extracted from this PDF. You can enter transactions manually instead.",
          );
        }
      } catch (e) {
        // Parse failure / unavailable parser: show the message + manual entry.
        setUploadError(
          `${errorMessage(
            e,
            "The expense summary could not be imported.",
          )} You can enter transactions manually instead.`,
        );
      } finally {
        setUploading(false);
      }
    },
    [propertyId, taxYear],
  );

  const handleSaveDraft = useCallback(
    async (draftId: string, changes: DraftChanges) => {
      if (!sessionId) return;
      const updated = await clientRef.current.updateDraft(
        sessionId,
        draftId,
        changes,
      );
      setDrafts((prev) =>
        prev.map((d) => (d.id === updated.id ? updated : d)),
      );
    },
    [sessionId],
  );

  const handleRemoveDraft = useCallback(
    async (draftId: string) => {
      if (!sessionId) return;
      await clientRef.current.removeDraft(sessionId, draftId);
      setDrafts((prev) => prev.filter((d) => d.id !== draftId));
    },
    [sessionId],
  );

  const handleConfirm = useCallback(async () => {
    if (!sessionId) return;
    setConfirming(true);
    setUploadError(null);
    try {
      const result = await clientRef.current.confirmImport(sessionId);
      setOutcome(result);
      // Refresh drafts so retained/incomplete ones reflect the latest state.
      const remaining = await clientRef.current.listDrafts(sessionId);
      setDrafts(remaining);
    } catch (e) {
      setUploadError(errorMessage(e, "Could not confirm the import."));
    } finally {
      setConfirming(false);
    }
  }, [sessionId]);

  return (
    <section aria-labelledby="import-heading">
      <h2
        id="import-heading"
        className="text-xl font-semibold text-fg"
      >
        Import expense summary
      </h2>
      <p className="mt-1 text-sm text-fg-subtle">
        Property: {propertyId} · Tax year: {taxYear}
      </p>

      <div className="mt-4">
        <label
          htmlFor="import-pdf"
          className="text-sm font-medium text-fg-muted"
        >
          Expense summary PDF
        </label>
        <input
          id="import-pdf"
          type="file"
          accept="application/pdf"
          disabled={uploading}
          onChange={(e) => {
            const file = e.target.files?.[0] ?? null;
            void handleFileChange(file);
          }}
          className="mt-1 block text-sm"
        />
        {uploading && (
          <p role="status" className="mt-2 text-sm text-fg-muted">
            Uploading and parsing the expense summary…
          </p>
        )}
        {fileError && (
          <p role="alert" className="mt-2 text-sm text-danger">
            {fileError}
          </p>
        )}
        {uploadError && (
          <p role="alert" className="mt-2 text-sm text-danger">
            {uploadError}
          </p>
        )}
      </div>

      {sessionId && drafts.length > 0 && (
        <div className="mt-6">
          <h3 className="text-lg font-medium text-fg">
            Review drafts ({drafts.length})
          </h3>
          <p className="mt-1 text-sm text-fg-subtle">
            Complete any flagged fields, then confirm. Nothing is saved as a
            transaction until you confirm.
          </p>
          <ul className="mt-3 space-y-3">
            {drafts.map((draft) => (
              <DraftRow
                key={draft.id}
                draft={draft}
                categories={categories}
                onSave={handleSaveDraft}
                onRemove={handleRemoveDraft}
                disabled={confirming}
              />
            ))}
          </ul>

          <button
            type="button"
            onClick={() => void handleConfirm()}
            disabled={confirming}
            className="mt-4 rounded-md bg-success px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-50"
          >
            {confirming ? "Confirming…" : "Confirm import"}
          </button>
        </div>
      )}

      {outcome && (
        <div
          role="status"
          className="mt-6 rounded-md border border-border bg-surface-muted p-4"
        >
          <h3 className="text-lg font-medium text-fg">Import result</h3>
          <p className="mt-1 text-sm text-fg-muted">
            {outcome.converted_count} draft
            {outcome.converted_count === 1 ? "" : "s"} converted to
            transactions. {outcome.remaining_incomplete} remaining incomplete.
          </p>
          {outcome.rejected.length > 0 && (
            <div className="mt-3">
              <p className="text-sm font-medium text-fg">
                Rejected drafts:
              </p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-danger">
                {outcome.rejected.map((r) => (
                  <li key={r.draft_id}>
                    {r.field}: {r.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
