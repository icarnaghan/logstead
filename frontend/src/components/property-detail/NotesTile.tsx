import { useEffect, useState } from "react";
import { ApiError } from "../../api/properties";
import { isAsyncLoading, useAsyncResource } from "../../lib/useAsyncResource";
import { Button, Tile } from "../ui";

/** Inline-editable free-text note tile (backed by the notes API). */
export function NotesTile({
  propertyId,
  loadNote,
  saveNote,
}: {
  propertyId: string;
  loadNote: (propertyId: string, signal?: AbortSignal) => Promise<string>;
  saveNote: (propertyId: string, text: string) => Promise<string>;
}) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  // `undefined` until a save is attempted, so a load error shows until then.
  const [saveError, setSaveError] = useState<string | null | undefined>(
    undefined,
  );
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const {
    data: loadedNote,
    error: loadError,
    status,
  } = useAsyncResource((signal) => loadNote(propertyId, signal), {
    resetKeys: [propertyId],
    describeError: (err) =>
      err instanceof ApiError ? err.message : "Could not load the note.",
  });
  useEffect(() => {
    if (loadedNote !== null) setText(loadedNote);
  }, [loadedNote]);
  const loading = isAsyncLoading(status);
  const error = saveError === undefined ? loadError : saveError;
  async function handleSave() {
    setSaving(true);
    setSaveError(null);
    setSavedMessage(null);
    try {
      const saved = await saveNote(propertyId, text);
      setText(saved);
      setSavedMessage("Saved");
    } catch (err) {
      setSaveError(
        err instanceof ApiError ? err.message : "Could not save the note.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Tile title="Notes" headingId="tile-notes">
      {loading ? (
        <p className="text-sm text-fg-subtle" role="status">
          Loading note…
        </p>
      ) : (
        <div className="space-y-2">
          <label htmlFor="property-note" className="sr-only">
            Property note
          </label>
          <textarea
            id="property-note"
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              setSavedMessage(null);
            }}
            rows={4}
            placeholder="Add a note about this property…"
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          />
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={() => void handleSave()}
              disabled={saving}
            >
              {saving ? "Saving…" : "Save"}
            </Button>
            {savedMessage ? (
              <span role="status" className="text-sm text-success">
                {savedMessage}
              </span>
            ) : null}
          </div>
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
        </div>
      )}
    </Tile>
  );
}
