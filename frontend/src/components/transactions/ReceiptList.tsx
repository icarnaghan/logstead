import { useRef, useState } from "react";
import type { ReceiptDocument, TransactionsApi } from "../../api/transactions";

interface ReceiptListProps {
  api: TransactionsApi;
  propertyId: string;
  transactionId: string;
  receipts: readonly ReceiptDocument[];
  /** Re-fetch receipts after a successful attach/delete. */
  onChanged: () => void;
}

/**
 * Per-transaction receipts: attach a file via a pre-signed URL (request URL →
 * PUT bytes → refresh), and list/delete existing receipts (Requirement 5.8).
 * The pre-signed flow keeps binary uploads off the JSON API and directly on S3.
 */
export function ReceiptList({
  api,
  propertyId,
  transactionId,
  receipts,
  onChanged,
}: ReceiptListProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File) {
    setBusy(true);
    setError(null);
    try {
      const { upload_url } = await api.attachReceipt(
        propertyId,
        transactionId,
        file.name,
        file.type || "application/octet-stream",
      );
      await api.uploadToPresignedUrl(upload_url, file, file.type || undefined);
      onChanged();
    } catch {
      setError("Could not attach the document. Please try again.");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function handleDelete(documentId: string) {
    setBusy(true);
    setError(null);
    try {
      await api.deleteReceipt(propertyId, transactionId, documentId);
      onChanged();
    } catch {
      setError("Could not delete the document. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-2">
      <p className="text-xs font-medium text-fg-muted">Supporting documents</p>
      {receipts.length === 0 ? (
        <p className="text-xs text-fg-subtle">No documents attached.</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {receipts.map((receipt) => (
            <li
              key={receipt.id}
              className="flex items-center justify-between gap-2 text-xs text-fg-muted"
            >
              {receipt.download_url ? (
                <a
                  href={receipt.download_url}
                  className="text-accent underline underline-offset-2 hover:text-accent-hover"
                >
                  {receipt.filename}
                </a>
              ) : (
                <span>{receipt.filename}</span>
              )}
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleDelete(receipt.id)}
                className="rounded px-2 py-1 text-danger hover:bg-danger-subtle disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                Delete
                <span className="sr-only"> document {receipt.filename}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <label
        htmlFor={`receipt-input-${transactionId}`}
        className="mt-2 inline-block text-xs font-medium text-fg"
      >
        Attach a document
      </label>
      <input
        id={`receipt-input-${transactionId}`}
        ref={inputRef}
        type="file"
        disabled={busy}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void handleFile(file);
        }}
        className="mt-1 block text-xs text-fg-muted file:mr-2 file:rounded-md file:border-0 file:bg-surface-muted file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-fg-muted"
      />
      {error ? (
        <p role="alert" className="mt-1 text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
