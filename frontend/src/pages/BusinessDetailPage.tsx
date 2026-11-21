import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  getBusiness,
  ApiError,
  type BusinessWithLinks,
} from "../api/businesses";
import { entityTypeLabel } from "./BusinessesPage";
import { BusinessDocuments } from "../components/businesses/BusinessDocuments";
import { EditBusinessDialog } from "../components/businesses/EditBusinessDialog";
import { DeleteBusinessConfirm } from "../components/businesses/DeleteBusinessConfirm";
import {
  Button,
  Card,
  LoadingRegion,
  PageHeader,
  RefreshingIndicator,
  StateBlock,
  Tile,
  TileSkeleton,
  useFirstLoad,
  useOpenerFocusReturn,
} from "../components/ui";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { isAsyncLoading, useAsyncResource } from "../lib/useAsyncResource";
import { PageContainer } from "../components/PageContainer";

interface BusinessDetailPageProps {
  /** Test seam: single-business loader. Defaults to the real `getBusiness`. */
  load?: (id: string, signal?: AbortSignal) => Promise<BusinessWithLinks>;
}

/** A single labelled business field, omitted entirely when the value is blank. */
function Field({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-sm text-fg-muted">{label}</dt>
      <dd className="text-sm font-medium text-fg">{value}</dd>
    </div>
  );
}

/**
 * Business detail page (Requirements 3.2, 10.2, 10.3, 11.3, 11.4).
 *
 * Loads a single business via `getBusiness` (which carries `linked_properties`
 * resolved to names) and renders its legal details, the names of the properties
 * linked to it (never a raw id — Req 10.2, 10.3), its documents
 * (`BusinessDocuments`, Req 11.4), and Edit/Delete actions (Req 11.3). On a
 * successful delete the page navigates back to the businesses list.
 *
 * The structure mirrors {@link ./PropertyDetailPage}: an `aria-labelledby`
 * heading, a breadcrumb that ends at the resolved business name, explicit
 * loading/error states, and an injectable loader seam for tests.
 */
export default function BusinessDetailPage({
  load = getBusiness,
}: BusinessDetailPageProps) {
  const { businessId = "" } = useParams();
  const navigate = useNavigate();
  const {
    data: business,
    error,
    status,
    reload: refresh,
    setData: setBusiness,
  } = useAsyncResource((signal) => load(businessId, signal), {
    // Switching businesses must not show the previous one's data.
    resetKeys: [businessId],
    enabled: businessId !== "",
    describeError: (err) =>
      err instanceof ApiError ? err.message : "Could not load this business.",
  });
  const [editing, setEditing] = useState(false);
  const { rememberOpener, handleCloseAutoFocus } = useOpenerFocusReturn();
  const view = useFirstLoad({
    loading: isAsyncLoading(status),
    error,
    resetKey: businessId,
  });
  // Refreshes never clear `business`, so content stays mounted (14.2, 14.3).
  const loaded = view.showContent ? business : null;

  // The breadcrumb tail and heading show the resolved legal name once loaded,
  // falling back to a neutral label while loading or on error — never a raw id.
  const headingName = loaded ? loaded.legal_name : "Business";
  useDocumentTitle(headingName);

  return (
    <PageContainer>
      <section aria-labelledby="page-heading">
        <PageHeader
          breadcrumb={[
            { label: "Businesses", to: "/businesses" },
            { label: headingName },
          ]}
          title={headingName}
          actions={
            loaded ? (
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    rememberOpener();
                    setEditing(true);
                  }}
                >
                  Edit
                </Button>
                <DeleteBusinessConfirm
                  business={loaded}
                  onDeleted={() => navigate("/businesses")}
                />
              </div>
            ) : null
          }
        />

        {view.showSkeleton ? (
          <LoadingRegion label="Loading business" className="mt-4">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <TileSkeleton />
              <TileSkeleton />
            </div>
          </LoadingRegion>
        ) : null}

        {view.showError ? (
          <div className="mt-4">
            <StateBlock
              kind="error"
              compact={view.errorIsStale}
              title="Could not load this business"
              description={error ?? undefined}
              onRetry={() => void refresh()}
            />
          </div>
        ) : null}

        {view.refreshing ? <RefreshingIndicator className="mt-4" /> : null}

        {loaded ? (
          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Tile title="Details" headingId="tile-details">
              <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field
                  label="Entity type"
                  value={entityTypeLabel(loaded.entity_type)}
                />
                <Field label="EIN" value={loaded.ein} />
                <Field
                  label="Formation state"
                  value={loaded.formation_state}
                />
                <Field
                  label="Formation date"
                  value={loaded.formation_date}
                />
                <Field
                  label="Tax year end"
                  value={loaded.tax_year_end}
                />
                <Field
                  label="Business address"
                  value={loaded.business_address}
                />
                {loaded.note ? (
                  <div className="flex flex-col gap-0.5 sm:col-span-2">
                    <dt className="text-sm text-fg-muted">Note</dt>
                    <dd className="whitespace-pre-wrap text-sm font-medium text-fg">
                      {loaded.note}
                    </dd>
                  </div>
                ) : null}
              </dl>
            </Tile>

            <Tile title="Linked properties" headingId="tile-linked-properties">
              {loaded.linked_properties &&
              loaded.linked_properties.length > 0 ? (
                <ul className="space-y-1">
                  {loaded.linked_properties.map((property) => (
                    <li key={property.id} className="text-sm text-fg">
                      {property.name}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-fg-subtle">
                  No properties are linked to this business yet.
                </p>
              )}
            </Tile>

            <Card className="p-4 lg:col-span-2">
              <BusinessDocuments businessId={loaded.id} />
            </Card>
          </div>
        ) : null}

        {loaded ? (
          <EditBusinessDialog
            business={loaded}
            open={editing}
            onOpenChange={setEditing}
            onCloseAutoFocus={handleCloseAutoFocus}
            onUpdated={(updated) =>
              setBusiness((prev) => (prev ? { ...prev, ...updated } : prev))
            }
          />
        ) : null}
      </section>
    </PageContainer>
  );
}
