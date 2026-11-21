import { useCallback, useEffect, useId, useState } from "react";
import {
  listBusinesses as defaultListBusinesses,
  setPropertyBusiness as defaultSetPropertyBusiness,
  ApiError,
  type Business,
} from "../../api/businesses";

/** Sentinel value for the "No business" option (clears the link via null). */
const NO_BUSINESS = "";

interface PropertyBusinessSelectorProps {
  /** The property whose owning business is being set/changed/cleared. */
  propertyId: string;
  /**
   * The id of the business currently linked to the property, or `null` when
   * unlinked. Drives the initial selected option.
   */
  businessId?: string | null;
  /**
   * The `legal_name` of the currently linked business, when known. Shown as the
   * current association so the UI never surfaces a raw id (Requirement 10.1,
   * 10.3). Optional — when omitted the loaded business list resolves the name.
   */
  currentBusinessName?: string | null;
  /** Test seam: businesses loader. Defaults to the real `listBusinesses`. */
  loadBusinesses?: (signal?: AbortSignal) => Promise<Business[]>;
  /** Test seam: link setter. Defaults to the real `setPropertyBusiness`. */
  setLink?: (propertyId: string, businessId: string | null) => Promise<void>;
  /**
   * Optional callback fired after a successful set/change/clear with the new
   * businessId (or `null` when cleared), so a parent can refresh its view.
   */
  onChanged?: (businessId: string | null) => void;
}

/**
 * Property↔business owning-business selector (Requirements 9, 10.1, 10.3, 11.5).
 *
 * Renders the property's current owning business by its human-readable
 * `legal_name` (never a raw id) and a native `<select>` of the user's
 * businesses — each option labelled by `legal_name` — plus a "No business"
 * option that clears the link. Choosing a business calls
 * `setPropertyBusiness(propertyId, businessId)`; choosing "No business" calls it
 * with `null`. The business list is loaded via `listBusinesses` to populate the
 * options.
 *
 * Accessibility: the `<select>` has a programmatically associated `<label>`,
 * and load/save failures are announced through a `role="alert"` region.
 */
export function PropertyBusinessSelector({
  propertyId,
  businessId = null,
  currentBusinessName = null,
  loadBusinesses = defaultListBusinesses,
  setLink = defaultSetPropertyBusiness,
  onChanged,
}: PropertyBusinessSelectorProps) {
  const selectId = useId();
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [selected, setSelected] = useState<string>(businessId ?? NO_BUSINESS);
  const [linkedName, setLinkedName] = useState<string | null>(
    currentBusinessName,
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Keep local state in sync when the owning props change (e.g. after a parent
  // refetch of the property).
  useEffect(() => {
    setSelected(businessId ?? NO_BUSINESS);
  }, [businessId]);
  useEffect(() => {
    setLinkedName(currentBusinessName);
  }, [currentBusinessName]);

  // Load the user's businesses to populate the options.
  useEffect(() => {
    const controller = new AbortController();
    setLoadError(null);
    loadBusinesses(controller.signal)
      .then((rows) => {
        if (controller.signal.aborted) return;
        setBusinesses(rows);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setLoadError(
          err instanceof ApiError
            ? err.message
            : "Could not load your businesses.",
        );
      });
    return () => controller.abort();
  }, [loadBusinesses]);

  // Resolve the linked business name from the loaded list when a current
  // businessId is set but no explicit name was provided (Requirement 10.1).
  useEffect(() => {
    if (currentBusinessName) return;
    if (!businessId) {
      setLinkedName(null);
      return;
    }
    const match = businesses.find((b) => b.id === businessId);
    if (match) setLinkedName(match.legal_name);
  }, [businesses, businessId, currentBusinessName]);

  const handleChange = useCallback(
    async (event: React.ChangeEvent<HTMLSelectElement>) => {
      const value = event.target.value;
      const nextBusinessId = value === NO_BUSINESS ? null : value;
      setSelected(value);
      setSaveError(null);
      setSaving(true);
      try {
        await setLink(propertyId, nextBusinessId);
        // Reflect the new linked name (or cleared state) in the display.
        if (nextBusinessId === null) {
          setLinkedName(null);
        } else {
          const match = businesses.find((b) => b.id === nextBusinessId);
          setLinkedName(match ? match.legal_name : linkedName);
        }
        onChanged?.(nextBusinessId);
      } catch (err) {
        setSaveError(
          err instanceof ApiError
            ? err.message
            : "Could not update the owning business.",
        );
      } finally {
        setSaving(false);
      }
    },
    [businesses, linkedName, onChanged, propertyId, setLink],
  );

  return (
    <div className="space-y-2">
      <p className="text-sm text-fg-muted">
        Owning business:{" "}
        <span className="font-medium text-fg">
          {linkedName ?? "No business"}
        </span>
      </p>

      <label
        htmlFor={selectId}
        className="block text-sm font-medium text-fg-muted"
      >
        Owning business
      </label>
      <select
        id={selectId}
        value={selected}
        onChange={handleChange}
        disabled={saving}
        aria-describedby={
          saveError
            ? `${selectId}-save-error`
            : loadError
              ? `${selectId}-load-error`
              : undefined
        }
        className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
      >
        <option value={NO_BUSINESS}>No business</option>
        {businesses.map((business) => (
          <option key={business.id} value={business.id}>
            {business.legal_name}
          </option>
        ))}
      </select>

      {saving ? (
        <p className="text-sm text-fg-subtle" role="status">
          Saving…
        </p>
      ) : null}

      {loadError ? (
        <p
          id={`${selectId}-load-error`}
          role="alert"
          className="text-sm text-danger"
        >
          {loadError}
        </p>
      ) : null}

      {saveError ? (
        <p
          id={`${selectId}-save-error`}
          role="alert"
          className="text-sm text-danger"
        >
          {saveError}
        </p>
      ) : null}
    </div>
  );
}

export default PropertyBusinessSelector;
