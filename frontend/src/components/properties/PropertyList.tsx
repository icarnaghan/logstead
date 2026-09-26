import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { deleteProperty, ApiError, type Property } from "../../api/properties";
import { listPhotos, type PhotoWithUrl } from "../../api/photos";
import { Button, Card, ConfirmDialog, useToast } from "../ui";

interface PropertyListProps {
  properties: Property[];
  /** Called after a successful delete so the parent can drop the card. */
  onDeleted: (id: string) => void;
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
  loadPhotos: (propertyId: string) => Promise<PhotoWithUrl[]>;
}

/**
 * A single property tile: photo (or placeholder), name, address, and actions.
 *
 * The card fetches the property's photos and shows the first one; when none
 * exist (or the fetch fails) it falls back to a house/pin placeholder. Actions:
 * a "Dashboard" link into the property overview (`/properties/:id`) and a
 * "More" menu that keeps the guarded delete reachable (Requirements 2.6, 2.7).
 */
function PropertyCard({
  property,
  deleting,
  error,
  onDelete,
  loadPhotos,
}: PropertyCardProps) {
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    loadPhotos(property.id)
      .then((photos) => {
        if (active) setPhotoUrl(photos[0]?.display_url ?? null);
      })
      .catch(() => {
        if (active) setPhotoUrl(null);
      });
    return () => {
      active = false;
    };
  }, [loadPhotos, property.id]);

  // Close the "More" menu when clicking outside it.
  useEffect(() => {
    if (!menuOpen) return;
    function onDocClick(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [menuOpen]);

  const detailPath = `/properties/${property.id}`;

  return (
    <Card as="li" className="flex flex-col overflow-hidden">
      <div className="aspect-[3/2] w-full overflow-hidden bg-surface-muted">
        {photoUrl ? (
          <img
            src={photoUrl}
            alt={`Photo of ${property.name}`}
            className="h-full w-full object-cover"
          />
        ) : (
          <PropertyPhotoPlaceholder />
        )}
      </div>

      <div className="flex flex-1 flex-col p-4">
        <h3 className="text-base font-semibold text-fg">
          <Link
            to={detailPath}
            className="underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            {property.name}
          </Link>
        </h3>
        <p className="mt-1 text-sm text-fg-muted">{property.address_text}</p>
        {property.property_type ? (
          <p className="mt-1 text-xs text-fg-subtle">{property.property_type}</p>
        ) : null}

        <div className="mt-4 flex items-center gap-2">
          <Button asChild variant="primary" size="sm">
            <Link to={detailPath}>Dashboard</Link>
          </Button>

          <div className="relative" ref={menuRef}>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setMenuOpen((open) => !open)}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-label={`More actions for ${property.name}`}
            >
              More
            </Button>
            {menuOpen ? (
              <div
                role="menu"
                className="absolute right-0 z-10 mt-1 w-44 rounded-md border border-border bg-surface py-1 shadow-card"
              >
                <Link
                  to={detailPath}
                  role="menuitem"
                  className="block px-3 py-1.5 text-sm text-fg-muted hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  View details
                </Link>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false);
                    onDelete(property);
                  }}
                  disabled={deleting}
                  aria-label={`Delete ${property.name}`}
                  className="block w-full px-3 py-1.5 text-left text-sm text-fg-muted hover:bg-danger-subtle hover:text-danger disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  {deleting ? "Deleting…" : "Delete"}
                </button>
              </div>
            ) : null}
          </div>
        </div>

        {error ? (
          <p role="alert" className="mt-2 text-sm text-danger">
            {error}
          </p>
        ) : null}
      </div>
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

  function requestDelete(property: Property) {
    setPendingDelete(property);
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
    </>
  );
}
