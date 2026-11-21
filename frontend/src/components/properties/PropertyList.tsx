import { useEffect, useState } from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Link } from "react-router-dom";
import { deleteProperty, ApiError, type Property } from "../../api/properties";
import { listPhotos, type PhotoWithUrl } from "../../api/photos";
import { PhotoLightbox } from "../photos";
import {
  Button,
  Card,
  ConfirmDialog,
  useOpenerFocusReturn,
  useToast,
} from "../ui";
import { EditPropertyDialog } from "./EditPropertyDialog";

interface PropertyListProps {
  properties: Property[];
  /** Called after a successful delete so the parent can drop the card. */
  onDeleted: (id: string) => void;
  /** Called after a successful edit so the parent can refresh the card. */
  onUpdated: (property: Property) => void;
  /** Test seam: delete call. Defaults to the real `deleteProperty`. */
  remove?: (id: string) => Promise<void>;
  /**
   * Test seam: per-property photo loader. Defaults to the real `listPhotos`.
   * Used to show the first photo as the card image (or a placeholder).
   */
  loadPhotos?: (propertyId: string) => Promise<PhotoWithUrl[]>;
}

/**
 * A house/pin placeholder shown when a property has no photo yet.
 * Decorative only — the accessible name comes from the surrounding card link.
 */
function PropertyPhotoPlaceholder() {
  return (
    <div
      aria-hidden="true"
      className="flex h-full w-full items-center justify-center bg-surface-muted text-fg-subtle"
    >
      {/* Simple house/pin glyph; no chart or data-viz, just an icon. */}
      <svg
        viewBox="0 0 24 24"
        className="h-10 w-10"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M3 10.5 12 3l9 7.5" />
        <path d="M5 9.5V21h14V9.5" />
        <path d="M9.5 21v-6h5v6" />
      </svg>
    </div>
  );
}

interface PropertyCardProps {
  property: Property;
  deleting: boolean;
  error?: string;
  onDelete: (property: Property) => void;
  onEdit: (property: Property) => void;
  loadPhotos: (propertyId: string) => Promise<PhotoWithUrl[]>;
}

/**
 * A single property tile: photo (or placeholder), name, address, and actions.
 *
 * The card fetches the property's photos and shows the chosen cover (or the
 * first photo when none is marked); clicking it opens a full-size lightbox.
 * When no photo exists (or the fetch fails) it falls back to a placeholder.
 * Actions:
 * a "Dashboard" link into the property overview (`/properties/:id`) and a
 * "More" menu that keeps the guarded delete reachable (Requirements 2.6, 2.7).
 */
function PropertyCard({
  property,
  deleting,
  error,
  onDelete,
  onEdit,
  loadPhotos,
}: PropertyCardProps) {
  const [cover, setCover] = useState<PhotoWithUrl | null>(null);
  const [lightboxOpen, setLightboxOpen] = useState(false);

  useEffect(() => {
    let active = true;
    loadPhotos(property.id)
      .then((photos) => {
        // Prefer the chosen cover; fall back to the first-listed photo.
        if (active) {
          setCover(photos.find((p) => p.photo.is_cover) ?? photos[0] ?? null);
        }
      })
      .catch(() => {
        if (active) setCover(null);
      });
    return () => {
      active = false;
    };
  }, [loadPhotos, property.id]);

  const detailPath = `/properties/${property.id}`;

  return (
    <Card as="li" className="flex flex-col overflow-hidden">
      <div className="aspect-[3/2] w-full overflow-hidden bg-surface-muted">
        {cover ? (
          <button
            type="button"
            onClick={() => setLightboxOpen(true)}
            aria-label={`View photo of ${property.name} larger`}
            className="block h-full w-full focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
          >
            <img
              src={cover.display_url}
              alt={property.name}
              className="h-full w-full object-cover"
            />
          </button>
        ) : (
          <PropertyPhotoPlaceholder />
        )}
      </div>

      <div className="flex flex-1 flex-col p-4">
        <h2 className="text-base font-semibold text-fg">
          <Link
            to={detailPath}
            className="underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            {property.name}
          </Link>
        </h2>
        <p className="mt-1 text-sm text-fg-muted">{property.address_text}</p>
        {property.property_type ? (
          <p className="mt-1 text-xs text-fg-subtle">{property.property_type}</p>
        ) : null}

        <div className="mt-4 flex items-center gap-2">
          <Button asChild variant="primary" size="sm">
            <Link to={detailPath}>Dashboard</Link>
          </Button>

          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                aria-label={`More actions for ${property.name}`}
              >
                More
              </Button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content
                align="end"
                sideOffset={4}
                className="z-20 w-48 rounded-md border border-border bg-surface py-1 shadow-card focus:outline-none"
              >
                <DropdownMenu.Item asChild>
                  <button
                    type="button"
                    onClick={() => onEdit(property)}
                    aria-label={`Edit ${property.name}`}
                    className="block w-full cursor-pointer px-3 py-1.5 text-left text-sm text-fg-muted outline-none data-[highlighted]:bg-surface-muted data-[highlighted]:text-fg"
                  >
                    Edit property
                  </button>
                </DropdownMenu.Item>
                <DropdownMenu.Item asChild>
                  <Link
                    to={`${detailPath}/assets`}
                    className="block px-3 py-1.5 text-sm text-fg-muted outline-none data-[highlighted]:bg-surface-muted data-[highlighted]:text-fg"
                  >
                    Depreciable assets
                  </Link>
                </DropdownMenu.Item>
                <DropdownMenu.Item asChild>
                  <Link
                    to={detailPath}
                    className="block px-3 py-1.5 text-sm text-fg-muted outline-none data-[highlighted]:bg-surface-muted data-[highlighted]:text-fg"
                  >
                    View details
                  </Link>
                </DropdownMenu.Item>
                <DropdownMenu.Item asChild>
                  <button
                    type="button"
                    onClick={() => onDelete(property)}
                    disabled={deleting}
                    aria-label={`Delete ${property.name}`}
                    className="block w-full cursor-pointer px-3 py-1.5 text-left text-sm text-fg-muted outline-none disabled:opacity-60 data-[highlighted]:bg-danger-subtle data-[highlighted]:text-danger"
                  >
                    {deleting ? "Deleting…" : "Delete"}
                  </button>
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        </div>

        {error ? (
          <p role="alert" className="mt-2 text-sm text-danger">
            {error}
          </p>
        ) : null}
      </div>

      {cover ? (
        <PhotoLightbox
          open={lightboxOpen}
          onOpenChange={setLightboxOpen}
          src={cover.display_url}
          alt={`Photo of ${property.name}`}
        />
      ) : null}
    </Card>
  );
}

/**
 * Accessible properties grid (Requirements 2.3, 2.6, 2.7).
 *
 * Renders the user's properties as a responsive grid of photo cards. Each card
 * shows the property's first photo (or a placeholder), its name (linking to the
 * property dashboard at `/properties/:id`), the address, and actions. Deletion
 * is guarded: when the backend rejects it because associated records exist it
 * returns a 409 conflict, and that message is surfaced inline on the card
 * (Requirement 2.7) rather than silently failing.
 */
export function PropertyList({
  properties,
  onDeleted,
  onUpdated,
  remove = deleteProperty,
  loadPhotos = listPhotos,
}: PropertyListProps) {
  const { notify } = useToast();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [cardErrors, setCardErrors] = useState<Record<string, string>>({});
  // The property awaiting delete confirmation, if any (ConfirmDialog is
  // controlled). Clicking Delete in the More menu opens the dialog; only
  // confirming performs the deletion (Requirements 4.1–4.3).
  const [pendingDelete, setPendingDelete] = useState<Property | null>(null);
  // The property currently being edited (controls the edit dialog), if any.
  const [editing, setEditing] = useState<Property | null>(null);

  function requestDelete(property: Property) {
    setPendingDelete(property);
  }

  const { rememberOpener, handleCloseAutoFocus } = useOpenerFocusReturn();

  function requestEdit(property: Property) {
    rememberOpener();
    setEditing(property);
  }

  function handleUpdated(property: Property) {
    onUpdated(property);
    setEditing(null);
    notify({ variant: "success", title: "Property updated" });
  }

  async function confirmDelete() {
    const property = pendingDelete;
    if (!property) return;
    setCardErrors((prev) => {
      const next = { ...prev };
      delete next[property.id];
      return next;
    });
    setDeletingId(property.id);
    try {
      await remove(property.id);
      setPendingDelete(null);
      onDeleted(property.id);
      notify({ variant: "success", title: "Property deleted" });
    } catch (err) {
      const isConflict = err instanceof ApiError && err.status === 409;
      const message = isConflict
        ? err.message ||
          "Remove associated transactions and assets before deleting this property."
        : err instanceof ApiError
          ? err.message
          : "Could not delete the property.";
      // Keep the inline conflict message on the card (Requirement 2.7) …
      setCardErrors((prev) => ({ ...prev, [property.id]: message }));
      // … and also surface a failure toast (Requirement 5.4).
      notify({
        variant: "error",
        title: "Could not delete property",
        description: message,
      });
      setPendingDelete(null);
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <>
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {properties.map((property) => (
          <PropertyCard
            key={property.id}
            property={property}
            deleting={deletingId === property.id}
            error={cardErrors[property.id]}
            onDelete={requestDelete}
            onEdit={requestEdit}
            loadPhotos={loadPhotos}
          />
        ))}
      </ul>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title="Delete property"
        description={
          pendingDelete
            ? `Delete "${pendingDelete.name}"? This permanently removes the property and cannot be undone.`
            : ""
        }
        confirmLabel="Delete"
        onConfirm={confirmDelete}
        pending={pendingDelete !== null && deletingId === pendingDelete.id}
      />

      {editing ? (
        <EditPropertyDialog
          property={editing}
          open={editing !== null}
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
          onUpdated={handleUpdated}
          onCloseAutoFocus={handleCloseAutoFocus}
        />
      ) : null}
    </>
  );
}
