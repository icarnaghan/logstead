import { useParams, useSearchParams } from "react-router-dom";
import {
  yearEndChecklistApi,
  type YearEndChecklist,
} from "../api/yearEndChecklist";
import { isAsyncLoading, useAsyncResource } from "../lib/useAsyncResource";
import { latestCompletedTaxYear, parseYearParam } from "../lib/taxYears";
import { usePropertyYearRange } from "../lib/usePropertyYearRange";
import { PageContainer } from "../components/PageContainer";
import { PropertySection } from "../components/PropertySection";
import { YearEndDisclaimer } from "../components/year-end-checklist/YearEndDisclaimer";
import { YearEndItemRow } from "../components/year-end-checklist/YearEndItemRow";
import {
  countsText,
  orderItems,
} from "../components/year-end-checklist/yearEndText";
import {
  LoadingRegion,
  RefreshingIndicator,
  Select,
  StateBlock,
  TableSkeleton,
  useFirstLoad,
} from "../components/ui";

/** Injectable API seam for tests. */
interface YearEndChecklistApiLike {
  getChecklist: (
    propertyId: string,
    taxYear: number,
    signal?: AbortSignal,
  ) => Promise<YearEndChecklist>;
}

interface YearEndChecklistPageProps {
  api?: YearEndChecklistApiLike;
}

const NO_ASSETS: readonly { placed_in_service_date: string }[] = [];

/**
 * Read-only Year-end checklist for one property and tax year. The year comes
 * from `?year=` (falling back to the latest completed tax year) and is
 * written back to the URL on change.
 */
export default function YearEndChecklistPage({
  api = yearEndChecklistApi,
}: YearEndChecklistPageProps = {}) {
  const { propertyId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const taxYear =
    parseYearParam(searchParams.get("year")) ?? latestCompletedTaxYear();

  const rangeYears = usePropertyYearRange(propertyId, NO_ASSETS);
  const yearOptions = rangeYears.includes(taxYear)
    ? rangeYears
    : [...rangeYears, taxYear].sort((a, b) => b - a);

  const {
    data: checklist,
    error,
    status,
    reload,
  } = useAsyncResource(
    (signal) => api.getChecklist(propertyId, taxYear, signal),
    {
      resetKeys: [propertyId],
      deps: [taxYear],
      enabled: propertyId !== "",
      describeError: () => "Unable to load the year-end checklist.",
    },
  );

  const view = useFirstLoad({
    loading: isAsyncLoading(status),
    error,
    resetKey: propertyId,
  });

  function handleYearChange(value: string) {
    const next = new URLSearchParams(searchParams);
    next.set("year", value);
    setSearchParams(next, { replace: true });
  }

  const items = checklist ? orderItems(checklist.items) : [];

  return (
    <PageContainer>
      <PropertySection
        propertyId={propertyId}
        title="Year-end checklist"
        description="Check that this property's records are complete and consistent for the selected tax year."
      />
      <YearEndDisclaimer />
      <div className="mt-6 space-y-6">
        <div className="flex flex-wrap items-center gap-2">
          <label
            htmlFor="year-end-year"
            className="text-sm font-medium text-fg-muted"
          >
            Tax year
          </label>
          <Select
            id="year-end-year"
            value={String(taxYear)}
            onChange={(event) => handleYearChange(event.target.value)}
          >
            {yearOptions.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </Select>
        </div>

        <div role="status" aria-live="polite" className="text-sm text-fg">
          {view.showContent && checklist ? countsText(checklist.counts) : null}
        </div>

        {view.showSkeleton ? (
          <LoadingRegion label="Loading checklist" className="space-y-4">
            <TableSkeleton columns={3} />
          </LoadingRegion>
        ) : null}
        {view.showError ? (
          <StateBlock
            kind="error"
            compact={view.errorIsStale}
            title="Could not load the checklist"
            description={error ?? undefined}
            onRetry={() => void reload()}
          />
        ) : null}
        {view.refreshing ? <RefreshingIndicator /> : null}
        {view.showContent && checklist ? (
          items.length === 0 ? (
            <StateBlock
              kind="empty"
              title="Nothing to check"
              description={`There are no checklist items for ${taxYear}.`}
            />
          ) : (
            <ul className="space-y-3">
              {items.map((item) => (
                <YearEndItemRow key={item.id} item={item} />
              ))}
            </ul>
          )
        ) : null}
      </div>
    </PageContainer>
  );
}
