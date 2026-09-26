import { useRef, useState } from "react";
import { getUserProfile } from "../lib/auth";
import { Button, Card, ConfirmDialog, useToast } from "../components/ui";
import {
  ApiError,
  clearData,
  fetchBackup,
  restoreBackup,
  type BackupDocument,
} from "../api/backup";
import sampleBackup from "../data/sample-backup.json";

/**
 * The bundled sample fixture, cast to {@link BackupDocument}. The JSON import
 * widens `type` (and other string-literal fields) to `string`, so the cast is
 * required for it to satisfy the document's more specific field types before it
 * is handed to the shared restore flow (Requirement 10.5).
 */
const SAMPLE_BACKUP = sampleBackup as BackupDocument;

/**
 * Triggers a browser download of `content` as a file named `filename` with the
 * given MIME type, using a Blob + object URL. Mirrors the identical helper in
 * `ReportsPage` so client-side downloads behave consistently across the app.
 */
function downloadFile(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** Local-date `YYYY-MM-DD` stamp used in the backup filename. */
function localDateStamp(date: Date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/**
 * Which restore document a pending confirm dialog will apply. `null` means the
 * restore dialog is closed. A document either came from an uploaded file or
 * from the bundled sample fixture; both take the identical confirm → restore
 * path (Requirements 6, 10.5, 10.6).
 */
type PendingRestore = { doc: BackupDocument } | null;

/**
 * Profile & settings page.
 *
 * Shows the signed-in user's account information (read from the Cognito ID
 * token claims), documents where integration settings live, and hosts the
 * Backup & restore controls (export, restore-from-file, clear, load sample).
 * Authentication is delegated to Cognito, so account fields such as email and
 * password are managed in the identity provider, not here.
 */
export default function ProfilePage() {
  const profile = getUserProfile();
  const { notify } = useToast();

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Download in-flight flag (disables the button + shows a pending label).
  const [downloading, setDownloading] = useState(false);
  // The document staged for a restore confirm dialog (file or sample), if any.
  const [pendingRestore, setPendingRestore] = useState<PendingRestore>(null);
  // Whether the destructive clear-all confirm dialog is open.
  const [clearOpen, setClearOpen] = useState(false);
  // Shared pending flag for a restore or clear write in flight.
  const [mutating, setMutating] = useState(false);

  async function handleDownload() {
    setDownloading(true);
    try {
      const document_ = await fetchBackup();
      downloadFile(
        JSON.stringify(document_, null, 2),
        `logstead-backup-${localDateStamp()}.json`,
        "application/json",
      );
      notify({ variant: "success", title: "Backup downloaded" });
    } catch {
      notify({ variant: "error", title: "Could not download the backup" });
    } finally {
      setDownloading(false);
    }
  }

  function handleRestoreClick() {
    fileInputRef.current?.click();
  }

  async function handleFileSelected(
    event: React.ChangeEvent<HTMLInputElement>,
  ) {
    const file = event.target.files?.[0];
    // Reset the input so re-selecting the same file fires `change` again.
    event.target.value = "";
    if (!file) return;

    let parsed: BackupDocument;
    try {
      const text = await file.text();
      parsed = JSON.parse(text) as BackupDocument;
    } catch {
      // A malformed file is caught client-side; no request is made.
      notify({
        variant: "error",
        title: "Could not read the backup file",
        description: "The selected file is not valid JSON.",
      });
      return;
    }
    // Valid JSON: open the destructive confirm before touching any data.
    setPendingRestore({ doc: parsed });
  }

  function handleLoadSample() {
    setPendingRestore({ doc: SAMPLE_BACKUP });
  }

  async function confirmRestore() {
    if (!pendingRestore) return;
    const { doc } = pendingRestore;
    setMutating(true);
    try {
      await restoreBackup(doc);
      setPendingRestore(null);
      notify({ variant: "success", title: "Backup restored" });
    } catch (err) {
      // Surface the server-side validation message on a 400; otherwise a
      // generic failure toast.
      const description =
        err instanceof ApiError && err.status === 400 ? err.message : undefined;
      notify({
        variant: "error",
        title: "Could not restore the backup",
        description,
      });
    } finally {
      setMutating(false);
    }
  }

  async function confirmClear() {
    setMutating(true);
    try {
      await clearData();
      setClearOpen(false);
      notify({ variant: "success", title: "All data cleared" });
    } catch {
      notify({ variant: "error", title: "Could not clear your data" });
    } finally {
      setMutating(false);
    }
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-semibold text-fg">
        Profile &amp; settings
      </h1>
      <p className="mt-1 text-sm text-fg-muted">
        Your account details and integration settings.
      </p>

      <section aria-labelledby="account-heading" className="mt-8">
        <h2 id="account-heading" className="text-lg font-medium text-fg">
          Account
        </h2>
        <dl className="mt-3 divide-y divide-border rounded-md border border-border">
          <div className="flex justify-between gap-4 px-4 py-3">
            <dt className="text-sm text-fg-subtle">Email</dt>
            <dd className="text-sm font-medium text-fg">
              {profile?.email ?? "Not available"}
            </dd>
          </div>
        </dl>
        <p className="mt-2 text-xs text-fg-subtle">
          Sign-in and passwords are managed by the identity provider (Amazon
          Cognito), not in Logstead.
        </p>
      </section>

      <section aria-labelledby="integrations-heading" className="mt-8">
        <h2
          id="integrations-heading"
          className="text-lg font-medium text-fg"
        >
          Integrations
        </h2>
        <div className="mt-3 rounded-md border border-border px-4 py-3">
          <p className="text-sm font-medium text-fg">
            RentCast property enrichment
          </p>
          <p className="mt-1 text-sm text-fg-muted">
            Property data enrichment is powered by RentCast. Its API key is
            configured on the server as a deployment setting and is never stored
            in the browser or your account data. Enrichment is optional: adding
            a property always works even when it is unavailable.
          </p>
        </div>
        <div className="mt-3 rounded-md border border-border px-4 py-3">
          <p className="text-sm font-medium text-fg">
            Address autocomplete
          </p>
          <p className="mt-1 text-sm text-fg-muted">
            Address suggestions are provided by Amazon Location Service using the
            application&apos;s AWS permissions. No key configuration is required.
          </p>
        </div>
      </section>

      <section aria-labelledby="backup-heading" className="mt-8">
        <h2 id="backup-heading" className="text-lg font-medium text-fg">
          Backup &amp; restore
        </h2>
        <p className="mt-1 text-sm text-fg-muted">
          Download a portable copy of all your data, restore from a backup file,
          load sample data to explore the app, or clear everything and start
          over. Restoring or clearing replaces all of your current data.
        </p>

        <Card as="section" className="mt-3 divide-y divide-border">
          <div className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div>
              <p className="text-sm font-medium text-fg">Download backup</p>
              <p className="mt-1 text-sm text-fg-muted">
                Export all of your properties, transactions, assets, and usage
                data as a single JSON file.
              </p>
            </div>
            <Button
              type="button"
              variant="secondary"
              onClick={() => void handleDownload()}
              disabled={downloading}
            >
              {downloading ? "Downloading…" : "Download backup"}
            </Button>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div>
              <p className="text-sm font-medium text-fg">Restore from file</p>
              <p className="mt-1 text-sm text-fg-muted">
                Upload a previously downloaded backup. This replaces all of your
                current data.
              </p>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/json"
              className="sr-only"
              aria-hidden="true"
              tabIndex={-1}
              onChange={(event) => void handleFileSelected(event)}
            />
            <Button
              type="button"
              variant="secondary"
              onClick={handleRestoreClick}
            >
              Restore from file
            </Button>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div>
              <p className="text-sm font-medium text-fg">Load sample data</p>
              <p className="mt-1 text-sm text-fg-muted">
                Replace your data with a realistic sample dataset so you can
                explore Schedule E features without hand-entering records.
              </p>
            </div>
            <Button
              type="button"
              variant="secondary"
              onClick={handleLoadSample}
            >
              Load sample data
            </Button>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div>
              <p className="text-sm font-medium text-fg">Clear all data</p>
              <p className="mt-1 text-sm text-fg-muted">
                Permanently delete every property, transaction, asset, photo,
                and receipt in your account.
              </p>
            </div>
            <Button
              type="button"
              variant="danger"
              onClick={() => setClearOpen(true)}
            >
              Clear all data
            </Button>
          </div>
        </Card>
      </section>

      <ConfirmDialog
        open={pendingRestore !== null}
        onOpenChange={(open) => {
          if (!open) setPendingRestore(null);
        }}
        title="Restore this backup?"
        description="This replaces all of your current data with the contents of this backup. Records that are not in the backup will be permanently removed. This cannot be undone."
        confirmLabel="Restore"
        onConfirm={confirmRestore}
        pending={mutating}
      />

      <ConfirmDialog
        open={clearOpen}
        onOpenChange={(open) => {
          if (!open) setClearOpen(false);
        }}
        title="Clear all data?"
        description="This permanently deletes every property, transaction, asset, photo, and receipt in your account, including their stored files. This cannot be undone."
        confirmLabel="Clear all data"
        onConfirm={confirmClear}
        pending={mutating}
      />
    </div>
  );
}
