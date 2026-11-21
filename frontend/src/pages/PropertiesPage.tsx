import { useState } from "react";
import { listProperties, ApiError, type Property } from "../api/properties";
import { listPhotos, type PhotoWithUrl } from "../api/photos";
import { PropertyList } from "../components/properties/PropertyList";
import { AddPropertyDialog } from "../components/properties/AddPropertyDialog";
import {
  Button,
  EmptyGuide,
  LoadingRegion,
  PageHeader,
  RefreshingIndicator,
  StateBlock,
  TableSkeleton,
  useFirstLoad,
} from "../components/ui";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { isAsyncLoading, useAsyncResource } from "../lib/useAsyncResource";
import { useNewParam } from "../lib/useNewParam";
import { EMPTY_COPY, SAMPLE_DATA_LINK_LABEL } from "../lib/emptyCopy";
import { useShellProperties } from "../components/ShellPropertiesContext";

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
  useDocumentTitle("Properties");
  const {
    data: properties,
    error,
    status,
    reload: refresh,
    setData: setProperties,
  } = useAsyncResource((signal) => load(signal), {
    describeError: (err) =>
      err instanceof ApiError ? err.message : "Could not load your properties.",
  });
  const [addOpen, setAddOpen] = useState(false);
  const view = useFirstLoad({ loading: isAsyncLoading(status), error });
  useNewParam(() => setAddOpen(true), view.showContent);
  const { reload: reloadShell } = useShellProperties();
  // Refreshes never clear `properties`, so content stays mounted (14.2, 14.3).

  function handleCreated(property: Property) {
    setProperties((prev) => (prev ? [...prev, property] : [property]));
    reloadShell();
  }

  function handleDeleted(id: string) {
    setProperties((prev) => (prev ? prev.filter((p) => p.id !== id) : prev));
    reloadShell();
  }

  function handleUpdated(property: Property) {
    setProperties((prev) =>
      prev ? prev.map((p) => (p.id === property.id ? property : p)) : prev,
    );
    reloadShell();
  }

  const items = view.showContent ? (properties ?? []) : null;
  const hasProperties = items !== null && items.length > 0;

  return (
    <section aria-labelledby="page-heading">
      <PageHeader
        title="Properties"
        description="Manage your rental properties. Select a property to record its transactions, depreciable assets, and Schedule E report."
        actions={
          hasProperties ? (
            <Button type="button" variant="primary" onClick={() => setAddOpen(true)}>
              Add property
            </Button>
          ) : null
        }
      />
      <AddPropertyDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onCreated={handleCreated}
      />

      <div className="mt-6">
        {view.showSkeleton ? (
          <LoadingRegion label="Loading properties">
            <TableSkeleton columns={4} />
          </LoadingRegion>
        ) : null}

        {view.showError ? (
          <div className={view.errorIsStale ? "mb-4" : undefined}>
            <StateBlock
              kind="error"
              compact={view.errorIsStale}
              title="Could not load your properties"
              description={error ?? undefined}
              onRetry={() => void refresh()}
            />
          </div>
        ) : null}

        {view.refreshing ? <RefreshingIndicator className="mb-4" /> : null}

        {items !== null && items.length === 0 ? (
          <EmptyGuide
            title={EMPTY_COPY.properties.title}
            description={EMPTY_COPY.properties.description}
            primary={{
              label: EMPTY_COPY.properties.primaryLabel,
              onClick: () => setAddOpen(true),
            }}
            secondary={{
              label: SAMPLE_DATA_LINK_LABEL,
              to: "/profile?focus=backup",
            }}
          />
        ) : null}

        {items !== null && items.length > 0 ? (
          <PropertyList
            properties={items}
            onDeleted={handleDeleted}
            onUpdated={handleUpdated}
            loadPhotos={loadPhotos}
          />
        ) : null}
      </div>
    </section>
  );
}
