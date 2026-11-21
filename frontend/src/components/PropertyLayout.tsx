import { useCallback, useEffect, useState } from "react";
import { Outlet, useOutletContext, useParams } from "react-router-dom";
import { getProperty, type Property } from "../api/properties";
import { useFirstLoad } from "./ui";

/**
 * Load state for the shared property context (Requirement 2.1, 3.1).
 *
 * `"loading"` while the property fetch is in flight, `"loaded"` once the
 * property (and its human-readable name) is available, and `"error"` when the
 * fetch fails. The raw property id is never surfaced as user-facing content in
 * any state.
 */
export type PropertyLoadStatus = "loading" | "loaded" | "error";

/**
 * The value provided to a property's child routes via `<Outlet context>`.
 *
 * Children read this through {@link usePropertyContext} to present the property
 * by its name (never its raw UUID) and to react to load/error states without
 * each sub-page re-fetching the property on sibling navigation.
 */
export interface PropertyContext {
  /** The route's `:propertyId` param (machine id — not for display). */
  propertyId: string;
  /** Current load status of the property fetch. */
  status: PropertyLoadStatus;
  /** The loaded property; present only when `status === "loaded"`. */
  property?: Property;
  /** Latest load error message, if any. May be set while `property` is stale-but-shown. */
  error?: string | null;
  /** True while a refresh is in flight and the property is already shown. */
  refreshing?: boolean;
  /** Re-fetch the property without clearing what is currently shown. */
  retry?: () => void | Promise<unknown>;
}

interface PropertyLayoutProps {
  /**
   * Test seam: single-property loader. Defaults to the real `getProperty`,
   * matching the injectable-loader pattern used by `PropertyDetailPage`.
   */
  load?: (id: string, signal?: AbortSignal) => Promise<Property>;
}

/**
 * Layout route for `properties/:propertyId` (Requirements 2.1, 2.4, 3.1).
 *
 * Fetches the property once and provides `{ propertyId, status, property }` to
 * its child routes (the property detail page and the transactions/assets/
 * reports sub-pages) through React Router's `<Outlet context>`. This lets every
 * sub-page present the property by name — never its raw identifier — and share
 * a single fetch rather than re-fetching on sibling navigation.
 *
 * The layout itself only renders the `<Outlet />`; it deliberately does not
 * render the breadcrumb or heading. Task 7.5 updates `PropertySection` to
 * render those from the resolved name exposed here.
 */
export default function PropertyLayout({
  load = getProperty,
}: PropertyLayoutProps) {
  const { propertyId } = useParams<{ propertyId: string }>();
  const [property, setProperty] = useState<Property | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const view = useFirstLoad({ loading, error, resetKey: propertyId });

  // A different property id must never show the previous property's data.
  const [prevId, setPrevId] = useState(propertyId);
  if (prevId !== propertyId) {
    setPrevId(propertyId);
    setProperty(undefined);
    setError(null);
    setLoading(true);
  }

  // Refreshes keep the loaded property mounted (Requirements 14.2, 14.3).
  const refresh = useCallback(
    (signal?: AbortSignal): Promise<void> => {
      if (!propertyId) return Promise.resolve();
      setLoading(true);
      setError(null);
      return load(propertyId, signal)
        .then((result) => {
          if (signal?.aborted) return;
          setProperty(result);
          setLoading(false);
        })
        .catch(() => {
          if (signal?.aborted) return;
          setError("Could not load this property.");
          setLoading(false);
        });
    },
    [propertyId, load],
  );

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  const hasProperty = view.showContent && property !== undefined;
  const status: PropertyLoadStatus = hasProperty
    ? "loaded"
    : error !== null
      ? "error"
      : "loading";

  const context: PropertyContext = {
    propertyId: propertyId ?? "",
    status,
    property: hasProperty ? property : undefined,
    error,
    refreshing: view.refreshing,
    retry: () => refresh(),
  };

  return <Outlet context={context} />;
}

/**
 * Read the property context provided by {@link PropertyLayout}.
 *
 * Resilient by design: when a page is rendered outside a `PropertyLayout`
 * outlet (for example, an existing page test that renders the page in isolation
 * without the layout), no outlet context is present. Rather than throwing —
 * which would break those standalone renders — this returns a safe default
 * (`{ propertyId: "", status: "loading" }`). Sub-pages that render standalone
 * continue to work because they read `propertyId` from `useParams` and use
 * their own loaders.
 */
export function usePropertyContext(): PropertyContext {
  const context = useOutletContext<PropertyContext | null>();
  return context ?? { propertyId: "", status: "loading" };
}
