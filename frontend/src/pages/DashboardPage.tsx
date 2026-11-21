import { lazy, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  dashboardApi as sharedApi,
  type DashboardApi,
  type DashboardSummary,
  type PropertyYearPoint,
  type TrendsSeries,
  type TrendYear,
} from "../api/dashboard";
import { DashboardEmptyState } from "../components/dashboard/DashboardEmptyState";
import { PageContainer } from "../components/PageContainer";
import { ChecklistCard } from "../components/dashboard/ChecklistCard";
import { DataTile } from "../components/dashboard/DataTile";
import { YearEndDashboardCard } from "../components/year-end-checklist/YearEndDashboardCard";
import {
  Button,
  Card,
  ChartSkeleton,
  LoadingRegion,
  PageHeader,
  StateBlock,
  Tile,
  TileSkeleton,
  useFirstLoad,
} from "../components/ui";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { latestCompletedTaxYear } from "../lib/taxYears";
import { formatMoneyWholeDollars, isLoss } from "../lib/money";
import { ChartCard } from "../components/charts/ChartCard";
import { LazyChart } from "../components/charts/LazyChart";
import {
  incomeExpenseNetTrend,
  netByPropertyTrend,
  depreciationTrend,
} from "../components/charts/prepare";
import { IncomeExpenseNetTrendTable } from "../components/charts/IncomeExpenseNetTrendTable";
import { NetByPropertyTrendTable } from "../components/charts/NetByPropertyTrendTable";
import { DepreciationTrendTable } from "../components/charts/DepreciationTrendTable";

/**
 * The three year-over-year trend charts are the lazy boundary for the trends
 * view: Recharts is reached only through these `React.lazy` imports, so it
 * code-splits into its own async chunk absent from the initial paint
 * (Requirement 10.1, 10.2). Each chart's always-present data table lives in a
 * Recharts-free module imported eagerly above and is passed as both the
 * `ChartCard.dataTable` and the `LazyChart.fallbackTable`.
 */
const IncomeExpenseNetTrendChart = lazy(
  () => import("../components/charts/IncomeExpenseNetTrendChart"),
);
const NetByPropertyTrendChart = lazy(
  () => import("../components/charts/NetByPropertyTrendChart"),
);
const DepreciationTrendChart = lazy(
  () => import("../components/charts/DepreciationTrendChart"),
);

interface DashboardPageProps {
  /** Injectable dashboard API for tests; defaults to the shared singleton. */
  api?: DashboardApi;
}

/**
 * Needs-attention nudge (Requirements 9.5, 9.6): a link list of the
 * Latest_Data_Year's properties with no income recorded yet
 * (`total_income == "0.00"`), each a navigation link into that property's
 * detail page. When every property has recorded income, a positive
 * confirmation is shown instead. Derived from the last `TrendYear`'s
 * per-property points.
 */
function NeedsAttentionNudge({ year }: { year: TrendYear }) {
  const zeroIncome = year.properties.filter(
    (property) => property.total_income === "0.00",
  );
  return (
    <Tile title="Needs attention" headingId="tile-attention">
      {zeroIncome.length === 0 ? (
        <p className="text-sm text-success">
          All properties have recorded income.
        </p>
      ) : (
        <>
          <p className="text-sm text-fg-muted">
            No income recorded yet in {year.tax_year}:
          </p>
          <ul className="mt-2 space-y-1">
            {zeroIncome.map((property) => (
              <li key={property.property_id}>
                <Link
                  to={`/properties/${property.property_id}`}
                  className="text-sm font-medium text-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  {property.property_name}
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </Tile>
  );
}

/**
 * Depreciation summary tile (Requirement 12): the Latest_Data_Year's
 * `depreciation_total` formatted via `formatMoneyWholeDollars`, plus a count of that year's
 * per-property points with a non-zero depreciation contribution. Derived from
 * the last `TrendYear` so it reconciles exactly with the depreciation trend's
 * last point.
 *
 * A per-property point's depreciation contribution for the year is its
 * depreciation portion of the portfolio total. The series does not carry a
 * per-property depreciation field, so a point is counted as having a non-zero
 * depreciation contribution when its figures reflect recorded data for the
 * year — i.e. its net differs from a strict "0.00" no-data point. The reconciled
 * total is the authoritative figure; the count is a supporting nudge.
 */
function DepreciationSummaryTile({ year }: { year: TrendYear }) {
  const withDepreciation = countDepreciatingProperties(year);
  return (
    <Tile title="Depreciation in service" headingId="tile-depreciation">
      <p className="tabular-nums text-2xl font-semibold text-fg">
        {formatMoneyWholeDollars(year.depreciation_total)}
      </p>
      <p className="mt-1 text-xs text-fg-subtle">
        Annual depreciation across the portfolio in {year.tax_year} (Schedule E
        Line 18).
      </p>
      <p className="mt-2 text-sm text-fg-muted">
        {withDepreciation}{" "}
        {withDepreciation === 1 ? "property" : "properties"} with depreciation
        this year.
      </p>
    </Tile>
  );
}

/**
 * Count the Latest_Data_Year's per-property points that contributed a non-zero
 * depreciation figure. The trends series exposes depreciation only at the
 * portfolio level (`depreciation_total`), so when the portfolio total is
 * exactly "0.00" no property depreciated and the count is 0; otherwise every
 * property point that carries recorded data for the year is counted.
 */
function countDepreciatingProperties(year: TrendYear): number {
  if (year.depreciation_total === "0.00") return 0;
  return year.properties.filter((point) => hasRecordedData(point)).length;
}

/**
 * Whether a per-property point reflects recorded data for its Data_Year. A
 * property with no data in a Data_Year appears with all three figures "0.00"
 * (Req 4.2, 11.3); any non-"0.00" income, expenses, or net means it has data.
 */
function hasRecordedData(point: PropertyYearPoint): boolean {
  return (
    point.total_income !== "0.00" ||
    point.total_expenses !== "0.00" ||
    point.net !== "0.00"
  );
}

/**
 * Properties launchpad (Requirements 9.5, 9.6): one navigation link per owned
 * property into its detail page, annotated with that property's
 * Latest_Data_Year `net`. A link list, not a per-property per-line data table.
 */
function PropertiesLaunchpad({ year }: { year: TrendYear }) {
  return (
    <Tile title="Properties" headingId="tile-launchpad" className="sm:col-span-2">
      <ul className="divide-y divide-border">
        {year.properties.map((property) => {
          const loss = isLoss(property.net);
          return (
            <li
              key={property.property_id}
              className="flex items-baseline justify-between gap-4 py-2"
            >
              <Link
                to={`/properties/${property.property_id}`}
                className="font-medium text-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                {property.property_name}
              </Link>
              <span
                className={[
                  "tabular-nums text-sm",
                  loss ? "text-danger" : "text-fg",
                ].join(" ")}
              >
                {formatMoneyWholeDollars(property.net)}
                {loss ? (
                  <span className="ml-1 text-xs font-medium uppercase tracking-wide text-danger">
                    {" "}
                    (loss)
                  </span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>
    </Tile>
  );
}

/** A single quicklink styled like a bordered nav pill. */
function QuickLink({ to, label }: { to: string; label: string }) {
  return (
    <Button asChild variant="secondary" size="sm">
      <Link to={to}>{label}</Link>
    </Button>
  );
}

/** Quick-actions tile: links to real routes only. */
function QuickActionsTile() {
  return (
    <Tile title="Quick actions" headingId="tile-actions">
      <div className="flex flex-wrap gap-2">
        <QuickLink to="/properties" label="Add property" />
        <QuickLink to="/properties" label="All properties" />
      </div>
    </Tile>
  );
}

/**
 * Latest-year headline (Requirement 1): a single net figure for the
 * Latest_Data_Year (the last entry of the trends series), labeled with that
 * four-digit year and formatted via {@link formatMoneyWholeDollars}. A negative net is
 * styled with the danger token plus a textual "Loss" cue so meaning never rests
 * on color alone ({@link isLoss}). Rendered only when the user owns properties
 * and the series has at least one Data_Year — the caller enforces that; this
 * component just renders the given year.
 */
function LatestYearHeadline({ year }: { year: TrendYear }) {
  const loss = isLoss(year.net);
  const label = loss ? "Net loss" : "Net income";
  return (
    <Card
      as="section"
      aria-label={`Portfolio net for ${year.tax_year}`}
      className="p-4 sm:col-span-2 lg:col-span-3"
    >
      <h2 className="text-sm font-medium text-fg-subtle">
        {label} ({year.tax_year})
      </h2>
      <p
        className={[
          "mt-2 text-3xl font-semibold tabular-nums",
          loss ? "text-danger" : "text-success",
        ].join(" ")}
      >
        {formatMoneyWholeDollars(year.net)}
        {loss ? (
          <span className="ml-2 align-middle text-xs font-medium uppercase tracking-wide text-danger">
            Loss
          </span>
        ) : null}
      </p>
    </Card>
  );
}

/**
 * The three year-over-year trend charts (Requirements 3, 4, 5), each inside a
 * {@link ChartCard} + {@link LazyChart}: the lazy Recharts chart is the visual
 * and the Recharts-free data table (passed as both `ChartCard.dataTable` and
 * `LazyChart.fallbackTable`) is always present in the DOM and is the fallback
 * on chart failure or below `sm` (Requirements 10.1, 10.2, 10.3, 10.5). The
 * series are derived from the single `getTrends()` fetch via the `prepare.ts`
 * builders, all crossing the money-string → integer-cents boundary via `toCents`.
 */
function TrendsSection({ series }: { series: TrendsSeries }) {
  const incomeExpenseNetData = incomeExpenseNetTrend(series);
  const netByPropertyData = netByPropertyTrend(series);
  const depreciationData = depreciationTrend(series);
  return (
    <>
      <div className="sm:col-span-2 lg:col-span-3">
        <ChartCard
          title="Income, expenses & net over time"
          ariaLabel="Portfolio income, expenses, and net for every year with data"
          chart={
            <LazyChart
              fallbackTable={
                <IncomeExpenseNetTrendTable data={incomeExpenseNetData} />
              }
            >
              <IncomeExpenseNetTrendChart data={incomeExpenseNetData} />
            </LazyChart>
          }
          dataTable={<IncomeExpenseNetTrendTable data={incomeExpenseNetData} />}
        />
      </div>

      <div className="sm:col-span-2 lg:col-span-3">
        <ChartCard
          title="Net contribution by property over time"
          ariaLabel="Net contribution per property for every year with data"
          chart={
            <LazyChart
              fallbackTable={
                <NetByPropertyTrendTable data={netByPropertyData} />
              }
            >
              <NetByPropertyTrendChart data={netByPropertyData} />
            </LazyChart>
          }
          dataTable={<NetByPropertyTrendTable data={netByPropertyData} />}
        />
      </div>

      <div className="sm:col-span-2 lg:col-span-3">
        <ChartCard
          title="Depreciation over time"
          ariaLabel="Portfolio depreciation (Schedule E Line 18) for every year with data"
          chart={
            <LazyChart
              fallbackTable={
                <DepreciationTrendTable data={depreciationData} />
              }
            >
              <DepreciationTrendChart data={depreciationData} />
            </LazyChart>
          }
          dataTable={<DepreciationTrendTable data={depreciationData} />}
        />
      </div>
    </>
  );
}

/** Skeleton for the trends region: headline, three charts, and the tiles. */
function TrendsSkeleton() {
  return (
    <LoadingRegion
      label="Loading dashboard"
      className="grid grid-cols-1 gap-4 sm:col-span-2 sm:grid-cols-2 lg:col-span-3 lg:grid-cols-3"
    >
      <TileSkeleton className="sm:col-span-2 lg:col-span-3" />
      <div className="sm:col-span-2 lg:col-span-3">
        <ChartSkeleton />
      </div>
      <TileSkeleton />
      <TileSkeleton />
      <TileSkeleton />
    </LoadingRegion>
  );
}

/**
 * Dashboard page — a portfolio-level, year-over-year trends view (Requirement
 * 9). It fetches the trends series once on mount and renders, in order: the
 * Latest_Data_Year headline (Req 1), three code-split trend charts (Req 3, 4,
 * 5), and the retained navigation tiles — a depreciation summary (Req 12), a
 * needs-attention nudge and a properties launchpad (Req 9.5, 9.6), plus quick
 * actions — all derived from the same single `getTrends()` series.
 *
 * Two empty/no-data states are distinguished (Req 8): a user who owns no
 * properties sees only the add-first-property {@link DashboardEmptyState}
 * (Req 8.1-8.3); a user who owns properties but has zero Data_Years sees a calm
 * no-data indication for the trends section — not an error — with no headline,
 * no charts, and none of the four tiles (Req 8.4-8.6, 12.5).
 */
export default function DashboardPage({ api = sharedApi }: DashboardPageProps) {
  useDocumentTitle("Dashboard");
  // Two independent data sources, each with its own loading/error state and
  // retry (Requirements 23.1-23.5). Refreshes never clear data, so content
  // stays mounted.
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [trends, setTrends] = useState<TrendsSeries | null>(null);
  const [trendsLoading, setTrendsLoading] = useState(true);
  const [trendsError, setTrendsError] = useState<string | null>(null);

  const loadDashboard = useCallback(
    async (signal?: AbortSignal) => {
      setSummaryLoading(true);
      setSummaryError(null);
      try {
        setSummary(await api.getDashboard(undefined, signal));
        setSummaryLoading(false);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setSummaryError("Your property summary did not load.");
        setSummaryLoading(false);
      }
    },
    [api],
  );

  const loadTrends = useCallback(
    async (signal?: AbortSignal) => {
      setTrendsLoading(true);
      setTrendsError(null);
      try {
        setTrends(await api.getTrends(signal));
        setTrendsLoading(false);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setTrendsError("Your portfolio trends did not load.");
        setTrendsLoading(false);
      }
    },
    [api],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadDashboard(controller.signal);
    return () => controller.abort();
  }, [loadDashboard]);

  useEffect(() => {
    const controller = new AbortController();
    void loadTrends(controller.signal);
    return () => controller.abort();
  }, [loadTrends]);

  const summaryView = useFirstLoad({
    loading: summaryLoading,
    error: summaryError,
  });
  const trendsView = useFirstLoad({
    loading: trendsLoading,
    error: trendsError,
  });

  // The Latest_Data_Year is the last entry of the series; null until trends
  // load or when the user has zero Data_Years.
  const latestYear =
    trends && trends.years.length > 0
      ? trends.years[trends.years.length - 1]
      : null;

  // Year for the Year-end checklist card: the headline year once trends load,
  // the latest completed year if trends failed, null while loading.
  const checklistYear = trendsView.showContent
    ? (latestYear?.tax_year ?? latestCompletedTaxYear())
    : trendsView.showError
      ? latestCompletedTaxYear()
      : null;
  const trendsStatus = trendsView.showContent
    ? "ready"
    : trendsView.showError
      ? "error"
      : "loading";

  return (
    <PageContainer>
      <section aria-labelledby="page-heading">
        <PageHeader
          title="Dashboard"
          description="Your portfolio at a glance, year over year."
        />

        {summaryView.showError && !summaryView.showContent ? (
          <div className="mt-6">
            <StateBlock
              kind="error"
              title="Could not load the dashboard"
              description={summaryError ?? undefined}
              onRetry={() => loadDashboard()}
            />
          </div>
        ) : summary && !summary.has_properties ? (
          <DashboardEmptyState prompt={summary.empty_state_prompt} />
        ) : (
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {summaryView.errorIsStale ? (
              <div className="sm:col-span-2 lg:col-span-3">
                <StateBlock
                  kind="error"
                  compact
                  title="Could not load the dashboard"
                  description={summaryError ?? undefined}
                  onRetry={() => loadDashboard()}
                />
              </div>
            ) : null}
            <ChecklistCard
              summary={summary}
              trends={trends}
              loading={!summaryView.showContent || trendsStatus === "loading"}
              error={trendsStatus === "error" && !trends}
            />
            <YearEndDashboardCard taxYear={checklistYear} />
            <DataTile
              status={trendsStatus}
              error={trendsError}
              onRetry={() => loadTrends()}
              skeleton={<TrendsSkeleton />}
            >
              {latestYear && trends ? (
                <>
                  <LatestYearHeadline year={latestYear} />
                  <TrendsSection series={trends} />
                  <DepreciationSummaryTile year={latestYear} />
                  <NeedsAttentionNudge year={latestYear} />
                  <PropertiesLaunchpad year={latestYear} />
                </>
              ) : (
                <p className="text-fg-muted sm:col-span-2 lg:col-span-3">
                  No data yet. Once you record income, expenses, or depreciation
                  for a tax year, your portfolio trends will appear here.
                </p>
              )}
            </DataTile>
            <QuickActionsTile />
          </div>
        )}
      </section>
    </PageContainer>
  );
}
