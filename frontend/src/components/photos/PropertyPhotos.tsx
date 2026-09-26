import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  ALLOWED_IMAGE_TYPES,
  ALLOWED_IMAGE_TYPES_LABEL,
  isAllowedImageType,
  PhotosApi,
  photosApi as defaultPhotosApi,
  type PhotoWithUrl,
} from "../../api/photos";
import { Button } from "../ui";

interface PropertyPhotosProps {
  /** The property whose photos are managed. */
  propertyId: string;
  /**
   * Photos API surface. Defaults to the shared instance; tests inject a double.
   */
  api?: Pick<
    PhotosApi,
    "listPhotos" | "requestUpload" | "deletePhoto" | "uploadToPresignedUrl"
  >;
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
 * Property photos manager (Requirement 4).
 *
 * Renders a labelled file input restricted to the accepted image types
 * (Requirement 4.2), performs the two-step pre-signed upload (request URL →
 * PUT bytes to S3 → refresh the list) (Requirement 4.1), displays the property's
 * photos in an accessible gallery with alt text (Requirement 4.3), and offers a
 * per-photo delete with confirmation (Requirement 4.4).
 *
 * Accessibility: the file input has an associated `<label>`, upload/validation
 * errors are announced via a `role="alert"` region, gallery images carry alt
 * text from the original filename, and every control is a real button with an
 * accessible name so it is keyboard operable.
 */
export function PropertyPhotos({
  propertyId,
  api = defaultPhotosApi,
  confirmDelete = (message) => window.confirm(message),
}: PropertyPhotosProps) {
  const [photos, setPhotos] = useState<PhotoWithUrl[]>([]);
  const [listStatus, setListStatus] = useState<Status>({ kind: "loading" });
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const fileInputId = useId();

  const refresh = useCallback(async () => {
    setListStatus({ kind: "loading" });
    try {
      const next = await api.listPhotos(propertyId);
      setPhotos(next);
      setListStatus({ kind: "idle" });
    } catch {
      setListStatus({
        kind: "error",
        message: "We couldn't load the photos for this property.",
      });
    }
  }, [api, propertyId]);

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

      // Client-side type validation before any network call (Requirement 4.2).
      if (!isAllowedImageType(file.type)) {
        setUploadError(
          `"${file.name}" is not an accepted image type. Accepted types are ${ALLOWED_IMAGE_TYPES_LABEL}.`,
        );
        return;
      }

      setIsUploading(true);
      try {
        const presigned = await api.requestUpload(
          propertyId,
          file.name,
          file.type,
        );
        await api.uploadToPresignedUrl(presigned.upload_url, file);
        await refresh();
      } catch {
        setUploadError(
          `We couldn't upload "${file.name}". Please try again.`,
        );
      } finally {
        setIsUploading(false);
      }
    },
    [api, propertyId, refresh],
  );

  const handleDelete = useCallback(
    async (item: PhotoWithUrl) => {
      const confirmed = confirmDelete(
        `Delete "${item.photo.original_filename}"? This can't be undone.`,
      );
      if (!confirmed) return;

      setUploadError(null);
      setDeletingId(item.photo.id);
      try {
        await api.deletePhoto(propertyId, item.photo.id);
        await refresh();
      } catch {
        setUploadError(
          `We couldn't delete "${item.photo.original_filename}". Please try again.`,
        );
      } finally {
        setDeletingId(null);
      }
    },
    [api, confirmDelete, propertyId, refresh],
  );

  return (
    <section aria-labelledby={`${fileInputId}-heading`} className="space-y-6">
      <div>
        <h2
          id={`${fileInputId}-heading`}
          className="text-lg font-semibold text-fg"
        >
          Photos
        </h2>
        <p className="mt-1 text-sm text-fg-subtle">
          Upload images to keep a visual record of this property. Accepted
          types: {ALLOWED_IMAGE_TYPES_LABEL}.
        </p>
      </div>

      <div className="space-y-2">
        <label
          htmlFor={fileInputId}
          className="block text-sm font-medium text-fg-muted"
        >
          Add a photo
        </label>
        <input
          ref={inputRef}
          id={fileInputId}
          type="file"
          accept={ALLOWED_IMAGE_TYPES.join(",")}
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
          Loading photos…
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
        (photos.length === 0 ? (
          <p className="text-sm text-fg-subtle">
            No photos yet. Add one above to get started.
          </p>
        ) : (
          <ul
            aria-label="Property photos"
            className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4"
          >
            {photos.map((item) => (
              <li
                key={item.photo.id}
                className="overflow-hidden rounded-md border border-border"
              >
                <img
                  src={item.display_url}
                  alt={item.photo.original_filename}
                  className="aspect-square w-full object-cover"
                />
                <div className="flex items-center justify-between gap-2 p-2">
                  <span className="truncate text-xs text-fg-muted">
                    {item.photo.original_filename}
                  </span>
                  <button
                    type="button"
                    onClick={() => void handleDelete(item)}
                    disabled={deletingId === item.photo.id}
                    className="shrink-0 rounded-md border border-danger px-2 py-1 text-xs font-medium text-danger hover:bg-danger-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger disabled:opacity-60"
                  >
                    {deletingId === item.photo.id
                      ? "Deleting…"
                      : `Delete ${item.photo.original_filename}`}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        ))}
    </section>
  );
}

export default PropertyPhotos;
