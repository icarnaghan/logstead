import { useState } from "react";
import { Link } from "react-router-dom";
import { listBusinesses, ApiError, type Business } from "../api/businesses";
import {
  Button,
  LoadingRegion,
  PageHeader,
  RefreshingIndicator,
  ResponsiveTable,
  StateBlock,
  TableSkeleton,
  useFirstLoad,
} from "../components/ui";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { isAsyncLoading, useAsyncResource } from "../lib/useAsyncResource";
import { AddBusinessDialog } from "../components/businesses/AddBusinessDialog";

interface BusinessesPageProps {
  /** Test seam: business loader. Defaults to the real `listBusinesses`. */
  load?: (signal?: AbortSignal) => Promise<Business[]>;
}

/**
 * Human-readable labels for the stored snake_case `entity_type` values
 * (Requirement 11.2). The wire stores the exact snake_case token; the UI never
 * surfaces the raw token where a human label exists. Unknown values fall back
 * to a title-cased rendering so the page never shows an empty cell.
 */
const ENTITY_TYPE_LABELS: Record<string, string> = {
  llc: "LLC",
  sole_proprietorship: "Sole proprietorship",
  partnership: "Partnership",
  s_corporation: "S corporation",
  c_corporation: "C corporation",
  individual_other: "Individual / other",
};

/** Render a stored `entity_type` as a human-readable label. */
export function entityTypeLabel(entityType: string): string {
  const known = ENTITY_TYPE_LABELS[entityType];
  if (known) return known;
  // Fallback: turn an unknown snake_case token into readable text.
  const spaced = entityType.replace(/_/g, " ").trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : entityType;
}

/**
 * Businesses list page (Requirements 11.1, 11.2).
 *
 * Fetches the authenticated user's businesses and renders each one's
 * `legal_name` (linking into its detail route) and a human-readable
 * `entity_type` label as an accessible, responsive table. When the user has no
 * businesses yet it shows an empty state prompting them to add their first one.
 * The loader is injectable via the `load` seam so tests can drive the page
 * without the network, mirroring {@link ./PropertiesPage}.
 */
export default function BusinessesPage({
  load = listBusinesses,
}: BusinessesPageProps) {
  useDocumentTitle("Businesses");
  const {
    data: businesses,
    error,
    status,
    reload: refresh,
    setData: setBusinesses,
  } = useAsyncResource((signal) => load(signal), {
    describeError: (err) =>
      err instanceof ApiError ? err.message : "Could not load your businesses.",
  });
  const [addOpen, setAddOpen] = useState(false);
  const view = useFirstLoad({ loading: isAsyncLoading(status), error });
  // Refreshes never clear `businesses`, so content stays mounted (14.2, 14.3).

  function handleCreated(business: Business) {
    setBusinesses((prev) => (prev ? [...prev, business] : [business]));
  }

  const items = view.showContent ? (businesses ?? []) : null;
  const hasBusinesses = items !== null && items.length > 0;

  return (
    <section aria-labelledby="page-heading">
      <PageHeader
        title="Businesses"
        description="Manage the business entities that own or operate your properties. Each business tracks its legal details and supporting documents."
        actions={
          hasBusinesses ? (
            <Button type="button" variant="primary" onClick={() => setAddOpen(true)}>
              Add business
            </Button>
          ) : null
        }
      />

      <div className="mt-6">
        {view.showSkeleton ? (
          <LoadingRegion label="Loading businesses">
            <TableSkeleton columns={2} />
          </LoadingRegion>
        ) : null}

        {view.showError ? (
          <div className={view.errorIsStale ? "mb-4" : undefined}>
            <StateBlock
              kind="error"
              compact={view.errorIsStale}
              title="Could not load your businesses"
              description={error ?? undefined}
              onRetry={() => void refresh()}
            />
          </div>
        ) : null}

        {view.refreshing ? <RefreshingIndicator className="mb-4" /> : null}

        {items !== null && items.length === 0 ? (
          <div>
            <StateBlock
              kind="empty"
              title="No businesses yet"
              description="Add your first business entity to track its legal details and documents."
            />
            <div className="mt-4 flex justify-center">
              <Button
                type="button"
                variant="primary"
                onClick={() => setAddOpen(true)}
              >
                Add business
              </Button>
            </div>
          </div>
        ) : null}

        {items !== null && items.length > 0 ? (
          <ResponsiveTable
            caption="Your businesses"
            columns={[
              { key: "legal_name", header: "Legal name" },
              { key: "entity_type", header: "Entity type" },
            ]}
            rows={items.map((business) => ({
              id: business.id,
              cells: {
                legal_name: (
                  <Link
                    to={`/businesses/${business.id}`}
                    className="underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  >
                    {business.legal_name}
                  </Link>
                ),
                entity_type: entityTypeLabel(business.entity_type),
              },
            }))}
          />
        ) : null}
      </div>
      <AddBusinessDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onCreated={handleCreated}
      />
    </section>
  );
}
