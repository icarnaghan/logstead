import { useCallback, useEffect, useState } from "react";
import { listProperties, ApiError, type Property } from "../api/properties";
import { listPhotos, type PhotoWithUrl } from "../api/photos";
import { PropertyList } from "../components/properties/PropertyList";
import { AddPropertyDialog } from "../components/properties/AddPropertyDialog";

type LoadState =
  | { status: "loading" }
  | { status: "loaded"; properties: Property[] }
  | { status: "error"; message: string };

interface PropertiesPageProps {
  /** Test seam: property loader. Defaults to the real `listProperties`. */
  load?: (signal?: AbortSignal) => Promise<Property[]>;
  /** Test seam: per-property photo loader passed to the property cards. */
  loadPhotos?: (propertyId: string) => Promise<PhotoWithUrl[]>;
}

/**
 * Properties list page (Requirements 2.1, 2.3, 2.6, 2.7, 3.x).
 *
 * Fetches the authenticated user's properties and renders them as an accessible
 * table with links into each property's sub-sections. When the user has no
 * properties yet it shows an empty state prompting them to add their first one.
 * The add-property flow (address autocomplete + RentCast enrichment with manual
 * fallback) lives in {@link AddPropertyDialog}; deletion is guarded and surfaces
 * a 409 conflict message inline via {@link PropertyList}.
 */
export default function PropertiesPage({
  load = listProperties,
  loadPhotos = listPhotos,
}: PropertiesPageProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  const refresh = useCallback(
    (signal?: AbortSignal) => {
      setState({ status: "loading" });
      load(signal)
        .then((properties) => setState({ status: "loaded", properties }))
        .catch((err) => {
          if (signal?.aborted) return;
          const message =
            err instanceof ApiError
              ? err.message
              : "Could not load your properties.";
          setState({ status: "error", message });
        });
    },
    [load],
  );

  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  function handleCreated(property: Property) {
    setState((prev) =>
      prev.status === "loaded"
        ? { status: "loaded", properties: [...prev.properties, property] }
        : { status: "loaded", properties: [property] },
    );
  }

  function handleDeleted(id: string) {
    setState((prev) =>
      prev.status === "loaded"
        ? {
            status: "loaded",
            properties: prev.properties.filter((p) => p.id !== id),
          }
        : prev,
    );
  }

  return (
    <section aria-labelledby="page-heading">
      <div className="flex items-center justify-between gap-4">
        <h1 id="page-heading" className="text-2xl font-semibold text-fg">
          Properties
        </h1>
        <AddPropertyDialog onCreated={handleCreated} />
      </div>

      <p className="mt-2 text-fg-muted">
        Manage your rental properties. Select a property to record its
        transactions, depreciable assets, and Schedule E report.
      </p>

      <div className="mt-6">
        {state.status === "loading" ? (
          <p className="text-fg-subtle" role="status">
            Loading properties…
          </p>
        ) : null}

        {state.status === "error" ? (
          <p role="alert" className="rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger">
            {state.message}
          </p>
        ) : null}

        {state.status === "loaded" && state.properties.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-8 text-center">
            <h2 className="text-lg font-medium text-fg">
              No properties yet
            </h2>
            <p className="mt-1 text-sm text-fg-subtle">
              Add your first rental property to start tracking income,
              expenses, and Schedule E reporting.
            </p>
            <div className="mt-4 flex justify-center">
              <AddPropertyDialog onCreated={handleCreated} />
            </div>
          </div>
        ) : null}

        {state.status === "loaded" && state.properties.length > 0 ? (
          <PropertyList
            properties={state.properties}
            onDeleted={handleDeleted}
            loadPhotos={loadPhotos}
          />
        ) : null}
      </div>
    </section>
  );
}
