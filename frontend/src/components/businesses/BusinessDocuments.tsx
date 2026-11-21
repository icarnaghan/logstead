import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  listDocuments as defaultListDocuments,
  requestDocumentUpload as defaultRequestDocumentUpload,
  uploadToPresignedUrl as defaultUploadToPresignedUrl,
  deleteDocument as defaultDeleteDocument,
  type BusinessDocumentWithUrl,
} from "../../api/businesses";
import { resolveContentType } from "../../lib/contentType";
import { Button } from "../ui";

/**
 * Accepted content types for business document uploads (Requirement 11.4).
 *
 * Broader than the image-only photo allow-list: business documents may be PDFs
 * in addition to the accepted image types. Kept in sync with the backend
 * `ALLOWED_DOCUMENT_TYPES` frozenset in `services/business.py`. Client-side
 * validation rejects anything outside this set before a pre-signed URL is ever
 * requested.
 */
export const ALLOWED_DOCUMENT_TYPES = [
  "application/pdf",
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/heic",
  "image/heif",
] as const;

export type AllowedDocumentType = (typeof ALLOWED_DOCUMENT_TYPES)[number];

/** Human-readable list of accepted types for validation messages. */
export const ALLOWED_DOCUMENT_TYPES_LABEL = "PDF, JPEG, PNG, WebP, HEIC, or HEIF";

/** True when `contentType` is one of the accepted document types. */
export function isAllowedDocumentType(contentType: string): boolean {
  return (ALLOWED_DOCUMENT_TYPES as readonly string[]).includes(contentType);
}

/**
 * Documents API surface consumed by this component. Mirrors the free functions
 * exported by `api/businesses`, but captured as an injectable object so tests
 * can supply doubles (the loader/upload/delete seams) without touching the
 * module singleton — the same pattern `PropertyPhotos` uses for its photos API.
 */
export interface BusinessDocumentsApi {
  listDocuments: (businessId: string) => Promise<BusinessDocumentWithUrl[]>;
  requestDocumentUpload: (
    businessId: string,
    filename: string,
    contentType: string,
  ) => Promise<{ upload_url: string }>;
  uploadToPresignedUrl: (url: string, file: File) => Promise<void>;
  deleteDocument: (businessId: string, documentId: string) => Promise<void>;
}

const defaultApi: BusinessDocumentsApi = {
  listDocuments: (businessId) => defaultListDocuments(businessId),
  requestDocumentUpload: (businessId, filename, contentType) =>
    defaultRequestDocumentUpload(businessId, filename, contentType),
  uploadToPresignedUrl: (url, file) => defaultUploadToPresignedUrl(url, file),
  deleteDocument: (businessId, documentId) =>
    defaultDeleteDocument(businessId, documentId),
};

interface BusinessDocumentsProps {
  /** The business whose documents are managed. */
  businessId: string;
  /**
   * Documents API surface. Defaults to the shared module functions; tests
   * inject doubles for the loader/upload/delete seams.
   */
  api?: BusinessDocumentsApi;
  /**
   * Confirmation hook for deletes. Defaults to `window.confirm`; tests can
   * override to avoid the native dialog.
   */
  confirmDelete?: (message: string) => boolean;
}

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string };

/**
 * Business documents manager (Requirement 11.4).
 *
 * Renders a labelled file input restricted to the accepted document types,
 * performs the two-step pre-signed upload (request URL → PUT bytes to S3 →
 * refresh the list), lists each document by its original filename with a
 * download link (the `download_url` from the API), and offers a per-document
 * delete with confirmation. Shows an empty state when there are no documents.
 *
 * Accessibility: the file input has an associated `<label>`, upload/validation
 * errors are announced via a `role="alert"` region, each list row exposes a
 * download link and a delete button with an accessible name, so every control
 * is keyboard operable.
 */
export function BusinessDocuments({
  businessId,
  api = defaultApi,
  confirmDelete = (message) => window.confirm(message),
}: BusinessDocumentsProps) {
  const [documents, setDocuments] = useState<BusinessDocumentWithUrl[]>([]);
  const [listStatus, setListStatus] = useState<Status>({ kind: "loading" });
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const fileInputId = useId();

  const refresh = useCallback(async () => {
    setListStatus({ kind: "loading" });
    try {
      const next = await api.listDocuments(businessId);
      setDocuments(next);
      setListStatus({ kind: "idle" });
    } catch {
      setListStatus({
        kind: "error",
        message: "We couldn't load the documents for this business.",
      });
    }
  }, [api, businessId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleFileChange = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      // Always clear the native input so selecting the same file again re-fires.
      event.target.value = "";
      if (!file) return;

      setUploadError(null);

      // Client-side type validation before any network call (Requirement 11.4).
      const contentType = resolveContentType(file, ALLOWED_DOCUMENT_TYPES);
      if (contentType === null) {
        setUploadError(
          `"${file.name}" is not an accepted document type. Accepted types are ${ALLOWED_DOCUMENT_TYPES_LABEL}.`,
        );
        return;
      }

      setIsUploading(true);
      try {
        const presigned = await api.requestDocumentUpload(
          businessId,
          file.name,
          contentType,
        );
        // The PUT's Content-Type must match the signed type.
        const body =
          file.type === contentType
            ? file
            : new File([file], file.name, { type: contentType });
        await api.uploadToPresignedUrl(presigned.upload_url, body);
        await refresh();
      } catch {
        setUploadError(`We couldn't upload "${file.name}". Please try again.`);
      } finally {
        setIsUploading(false);
      }
    },
    [api, businessId, refresh],
  );

  const handleDelete = useCallback(
    async (item: BusinessDocumentWithUrl) => {
      const confirmed = confirmDelete(
        `Delete "${item.document.original_filename}"? This can't be undone.`,
      );
      if (!confirmed) return;

      setUploadError(null);
      setDeletingId(item.document.id);
      try {
        await api.deleteDocument(businessId, item.document.id);
        await refresh();
      } catch {
        setUploadError(
          `We couldn't delete "${item.document.original_filename}". Please try again.`,
        );
      } finally {
        setDeletingId(null);
      }
    },
    [api, businessId, confirmDelete, refresh],
  );

  return (
    <section aria-labelledby={`${fileInputId}-heading`} className="space-y-6">
      <div>
        <h2
          id={`${fileInputId}-heading`}
          className="text-lg font-semibold text-fg"
        >
          Documents
        </h2>
        <p className="mt-1 text-sm text-fg-subtle">
          Upload supporting documents for this business. Accepted types:{" "}
          {ALLOWED_DOCUMENT_TYPES_LABEL}.
        </p>
      </div>

      <div className="space-y-2">
        <label
          htmlFor={fileInputId}
          className="block text-sm font-medium text-fg-muted"
        >
          Add a document
        </label>
        <input
          ref={inputRef}
          id={fileInputId}
          type="file"
          accept={ALLOWED_DOCUMENT_TYPES.join(",")}
          disabled={isUploading}
          onChange={handleFileChange}
          aria-describedby={uploadError ? `${fileInputId}-error` : undefined}
          className="block w-full text-sm text-fg-muted file:mr-4 file:rounded-md file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-accent-fg hover:file:bg-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
        />
        {isUploading && (
          <p className="text-sm text-fg-subtle" role="status">
            Uploading…
          </p>
        )}
        {uploadError && (
          <p
            id={`${fileInputId}-error`}
            role="alert"
            className="text-sm text-danger"
          >
            {uploadError}
          </p>
        )}
      </div>

      {listStatus.kind === "loading" && (
        <p className="text-sm text-fg-subtle" role="status">
          Loading documents…
        </p>
      )}

      {listStatus.kind === "error" && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-danger">
            {listStatus.message}
          </p>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => void refresh()}
          >
            Retry
          </Button>
        </div>
      )}

      {listStatus.kind === "idle" &&
        (documents.length === 0 ? (
          <p className="text-sm text-fg-subtle">
            No documents yet. Add one above to get started.
          </p>
        ) : (
          <ul
            aria-label="Business documents"
            className="divide-y divide-border rounded-md border border-border"
          >
            {documents.map((item) => (
              <li
                key={item.document.id}
                className="flex items-center justify-between gap-3 p-3"
              >
                <a
                  href={item.download_url}
                  download={item.document.original_filename}
                  className="truncate text-sm font-medium text-accent underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  {item.document.original_filename}
                </a>
                <button
                  type="button"
                  onClick={() => void handleDelete(item)}
                  disabled={deletingId === item.document.id}
                  className="shrink-0 rounded-md border border-danger px-2 py-1 text-xs font-medium text-danger hover:bg-danger-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger disabled:opacity-60"
                >
                  {deletingId === item.document.id
                    ? "Deleting…"
                    : `Delete ${item.document.original_filename}`}
                </button>
              </li>
            ))}
          </ul>
        ))}
    </section>
  );
}

export default BusinessDocuments;
