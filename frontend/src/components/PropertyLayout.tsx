import { useCallback, useEffect, useState } from "react";
import { Outlet, useOutletContext, useParams } from "react-router-dom";
import { getProperty, type Property } from "../api/properties";

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
  const [state, setState] = useState<{
    status: PropertyLoadStatus;
    property?: Property;
  }>({ status: "loading" });

  const refresh = useCallback(
    (signal?: AbortSignal) => {
      if (!propertyId) return;
      setState({ status: "loading" });
      load(propertyId, signal)
        .then((property) => setState({ status: "loaded", property }))
        .catch(() => {
          if (signal?.aborted) return;
          setState({ status: "error" });
        });
    },
    [propertyId, load],
  );

  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  const context: PropertyContext = {
    propertyId: propertyId ?? "",
    status: state.status,
    property: state.property,
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
