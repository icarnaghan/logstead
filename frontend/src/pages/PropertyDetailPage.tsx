import { useMemo, useState } from "react";
import {
  getPropertyNote,
  setPropertyNote,
  getEarliestDataYear,
  ApiError,
} from "../api/properties";
import { listPhotos, type PhotoWithUrl } from "../api/photos";
import { listAssets, type DepreciableAsset } from "../api/assets";
import type { ActivityListParams, ActivityPage } from "../api/activity";
import { getReport, type ScheduleEReport } from "../api/reports";
import { RecentActivityPanel } from "../components/activity/RecentActivityPanel";
import { PropertyDetailsView } from "../components/properties/PropertyDetailsView";
import { PropertyBusinessSelector } from "../components/businesses/PropertyBusinessSelector";
import { PropertyPhotos, PhotoLightbox } from "../components/photos";
import {
  Card,
  LoadingRegion,
  PageHeader,
  RefreshingIndicator,
  StateBlock,
  Tile,
  TileSkeleton,
  useFirstLoad,
} from "../components/ui";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { useAsyncResource } from "../lib/useAsyncResource";
import { usePropertyYearRange } from "../lib/usePropertyYearRange";
import { propertyPath } from "../components/navConfig";
import { PageContainer } from "../components/PageContainer";
import { usePropertyContext } from "../components/PropertyLayout";
import { PropertySectionTabs } from "../components/PropertySectionTabs";
import { resolvePropertyName } from "../components/propertyName";
import { DepreciationTile } from "../components/property-detail/DepreciationTile";
import { IncomeExpenseTile } from "../components/property-detail/IncomeExpenseTile";
import { NotesTile } from "../components/property-detail/NotesTile";
import { PropertyHeaderCard } from "../components/property-detail/PropertyHeaderCard";
import { QuickLink } from "../components/property-detail/QuickLink";
import { toReportState } from "../components/property-detail/reportState";
import { usePropertyAssets } from "../components/property-detail/usePropertyAssets";
import { usePropertyHeaderPhoto } from "../components/property-detail/usePropertyHeaderPhoto";
import {
  YearEndSummarySection,
  type YearEndSummarySectionProps,
} from "../components/year-end-checklist/YearEndSummarySection";

interface PropertyDetailPageProps {
  /** Test seam: Schedule E report loader. Defaults to the real `getReport`. */
  loadReport?: (propertyId: string, taxYear: number) => Promise<ScheduleEReport>;
  /** Test seam: per-property photo loader. Defaults to the real `listPhotos`. */
  loadPhotos?: (propertyId: string) => Promise<PhotoWithUrl[]>;
  /** Test seam: per-property asset loader (drives the tax-year range). */
  loadAssets?: (propertyId: string) => Promise<DepreciableAsset[]>;
  /** Test seam: earliest-activity-year loader. Defaults to `getEarliestDataYear`. */
  loadEarliestYear?: (
    propertyId: string,
    signal?: AbortSignal,
  ) => Promise<number | null>;
  /** Test seam: note loader. Defaults to the real `getPropertyNote`. */
  loadNote?: (propertyId: string, signal?: AbortSignal) => Promise<string>;
  /** Test seam: note saver. Defaults to the real `setPropertyNote`. */
  saveNote?: (propertyId: string, text: string) => Promise<string>;
  /** Test seam: year-end checklist summary loader. Defaults to the real API. */
  loadChecklistSummary?: YearEndSummarySectionProps["loadSummary"];
  /** Test seam: recent activity loader. Defaults to the real activity API. */
  loadActivity?: (
    propertyId: string,
    params?: ActivityListParams,
  ) => Promise<ActivityPage>;
}

/**
 * Per-property tiled dashboard (Requirement 2.9).
 *
 * Revamps the property overview into a REI-Hub-style grid of tiles for a single
 * property, driven by a tax-year selector at the top. Tiles cover the property
 * header (photo + name + address + type + photo upload), income/expenses/net
 * for the selected year (from the Schedule E report totals), depreciation (the
 * Line 18 total from the same report), a link to the full Schedule E report,
 * stored RentCast property details, a link to supporting documents
 * (transactions), an editable free-text note, and quicklinks into the
 * property's sub-sections. Money is rendered from its two-decimal string form
 * and never re-derived from a float.
 */
export default function PropertyDetailPage({
  loadReport = getReport,
  loadPhotos = listPhotos,
  loadAssets = listAssets,
  loadEarliestYear = getEarliestDataYear,
  loadNote = getPropertyNote,
  saveNote = setPropertyNote,
  loadChecklistSummary,
  loadActivity,
}: PropertyDetailPageProps) {
  // Identity and orientation come from the shared property context fetched once
  // by `PropertyLayout` (Requirements 4.1, 4.2) — the overview no longer issues
  // its own `getProperty` fetch. The resolved name is used for the breadcrumb
  // tail crumb and the single page `<h1>`, never the raw id (Requirement 1.3).
  const context = usePropertyContext();
  const propertyId = context.propertyId;
  const propertyName = resolvePropertyName(
    context.status,
    context.property?.name,
  );

  useDocumentTitle(`Overview - ${propertyName}`);

  // First-load-only skeleton; refreshes keep content mounted (14.1-14.3).
  const view = useFirstLoad({
    loading: context.status === "loading" || Boolean(context.refreshing),
    error: context.error ?? (context.status === "error" ? "" : null),
    resetKey: propertyId,
  });

  const headerPhoto = usePropertyHeaderPhoto(propertyId, loadPhotos);
  const [headerLightboxOpen, setHeaderLightboxOpen] = useState(false);

  // The latest filable tax year is the prior calendar year — the current year
  // isn't over yet, so it is never the default or an option.
  const latestTaxYear = useMemo(() => new Date().getFullYear() - 1, []);
  // Depreciable assets size the tax-year selector.
  const assets = usePropertyAssets(propertyId, loadAssets);
  // Tax years span from the property's earliest activity (transaction or asset
  // year) to the latest completed year.
  const years = usePropertyYearRange(propertyId, assets, loadEarliestYear);
  const [taxYear, setTaxYear] = useState<number>(latestTaxYear);
  // Every property or tax-year change resets to the loading state.
  const {
    data: loadedReport,
    error: reportError,
    status: reportStatus,
  } = useAsyncResource(() => loadReport(propertyId, taxYear), {
    resetKeys: [propertyId, taxYear],
    enabled: propertyId !== "",
    describeError: (err) =>
      err instanceof ApiError ? err.message : "Could not load the report.",
  });
  const report = toReportState(reportStatus, loadedReport, reportError);

  return (
    <PageContainer>
      <section aria-labelledby="page-heading">
        {/*
          Orientation header — rendered in every context state so the user never
          loses their place while the property loads or if it fails
          (Requirements 1.1, 1.2, 3.1–3.3). The breadcrumb ends at the resolved
          property name as the current, non-link crumb (Requirement 1.4), and
          the single page `<h1>` shows that same name.
        */}
        <PageHeader
          breadcrumb={[
            { label: "Properties", to: "/properties" },
            { label: propertyName },
          ]}
          title="Overview"
          meta={propertyName}
        >
          <PropertySectionTabs propertyId={propertyId} />
        </PageHeader>

        {view.showSkeleton ? (
          <LoadingRegion label="Loading property" className="mt-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <TileSkeleton />
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
              title="Could not load this property"
              description={context.error ?? undefined}
              onRetry={context.retry}
            />
          </div>
        ) : null}

        {view.refreshing ? <RefreshingIndicator className="mt-4" /> : null}

        {view.showContent && context.property ? (
          <>
            <PropertyHeaderCard
              property={context.property}
              photo={headerPhoto}
              onOpenPhoto={() => setHeaderLightboxOpen(true)}
              taxYear={taxYear}
              years={years}
              onTaxYearChange={setTaxYear}
            />

            {/* Tile grid. */}
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <IncomeExpenseTile report={report} />
              <DepreciationTile report={report} />

              <Tile title="Schedule E report" headingId="tile-report">
                <p className="text-sm text-fg-muted">
                  View the full Schedule E line-by-line report for the selected
                  tax year.
                </p>
                <div className="mt-3">
                  <QuickLink
                    to={propertyPath(context.property.id, "reports")}
                    label="Open report"
                  />
                </div>
              </Tile>

              <Tile title="Supporting documents" headingId="tile-documents">
                <p className="text-sm text-fg-muted">
                  Receipts and documents are attached to transactions.
                </p>
                <div className="mt-3">
                  <QuickLink
                    to={propertyPath(context.property.id, "transactions")}
                    label="View transactions"
                  />
                </div>
              </Tile>

              <NotesTile
                propertyId={context.property.id}
                loadNote={loadNote}
                saveNote={saveNote}
              />

              <Tile title="Owning business" headingId="tile-business">
                <PropertyBusinessSelector
                  propertyId={context.property.id}
                  businessId={context.property.business_id ?? null}
                />
              </Tile>

              <Tile
                title="Quicklinks"
                headingId="tile-quicklinks"
                className="sm:col-span-2 lg:col-span-1"
              >
                <div className="flex flex-wrap gap-2">
                  <QuickLink
                    to={propertyPath(context.property.id, "transactions")}
                    label="Transactions"
                  />
                  <QuickLink
                    to={propertyPath(context.property.id, "assets")}
                    label="Depreciable Assets"
                  />
                  <QuickLink
                    to={propertyPath(context.property.id, "reports")}
                    label="Schedule E Report"
                  />
                </div>
              </Tile>

              <Tile
                title="Property details"
                headingId="tile-details"
                className="sm:col-span-2 lg:col-span-3"
              >
                {context.property.details ? (
                  <PropertyDetailsView details={context.property.details} />
                ) : (
                  <p className="text-sm text-fg-subtle">
                    No additional property details are on file. Details are
                    added automatically when a property is created from an
                    address that RentCast has data for.
                  </p>
                )}
              </Tile>

              <Card className="p-4 sm:col-span-2 lg:col-span-3">
                <PropertyPhotos propertyId={context.property.id} />
              </Card>

              {headerPhoto ? (
                <PhotoLightbox
                  open={headerLightboxOpen}
                  onOpenChange={setHeaderLightboxOpen}
                  src={headerPhoto}
                  alt={`Photo of ${context.property.name}`}
                />
              ) : null}
            </div>

            <RecentActivityPanel
              propertyId={context.property.id}
              loadActivity={loadActivity}
            />
            <YearEndSummarySection
              propertyId={context.property.id}
              loadSummary={loadChecklistSummary}
            />
          </>
        ) : null}
      </section>
    </PageContainer>
  );
}
