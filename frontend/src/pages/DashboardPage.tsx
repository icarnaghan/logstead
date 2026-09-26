import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  dashboardApi as sharedApi,
  type DashboardApi,
  type DashboardSummary,
  type PropertySummary,
} from "../api/dashboard";
import {
  getCombinedReport,
  DEPRECIATION_LINE,
  type CombinedScheduleEReport,
} from "../api/reports";
import { listAssets, type DepreciableAsset } from "../api/assets";
import { TaxYearSelector } from "../components/dashboard/TaxYearSelector";
import { DashboardEmptyState } from "../components/dashboard/DashboardEmptyState";
import { formatMoney, isLoss, sumMoney } from "../components/dashboard/money";

interface DashboardPageProps {
  /** Injectable dashboard API for tests; defaults to the shared singleton. */
  api?: DashboardApi;
  /**
   * Injectable combined-report loader for tests; defaults to the real
   * {@link getCombinedReport}. Drives the Schedule E and depreciation tiles.
   */
  loadCombined?: (taxYear: number) => Promise<CombinedScheduleEReport>;
  /**
   * Injectable per-property asset loader for tests; defaults to the real
   * {@link listAssets}. Used to size the tax-year selector back to the
   * earliest in-service year across all properties.
   */
  loadAssets?: (propertyId: string) => Promise<DepreciableAsset[]>;
}

/**
 * Selectable tax years, newest first: from `earliestYear` (the earliest
 * depreciable-asset in-service year across the whole portfolio) through the
 * current year. When there are no assets, `earliestYear` is null and a
 * recent-years window (current back `fallbackCount`) is used so the selector is
 * never empty. A future-dated earliest year is capped at the current year.
 */
function taxYearRange(earliestYear: number | null, fallbackCount = 6): number[] {
  const current = new Date().getFullYear();
  let earliest = earliestYear ?? current - (fallbackCount - 1);
  earliest = Math.min(earliest, current);
  const span = Math.max(current - earliest + 1, 1);
  return Array.from({ length: span }, (_, index) => current - index);
}

/**
 * The Line 18 (depreciation) total for one property's Schedule E report,
 * defaulting to "0.00" when the property has no depreciation line.
 */
function depreciationOf(
  report: CombinedScheduleEReport["properties"][number],
): string {
  return (
    report.lines.find((line) => line.line === DEPRECIATION_LINE)?.total ??
    "0.00"
  );
}

/** Shared tile shell — a rounded surface card with a labelled heading. */
function Tile({
  title,
  headingId,
  children,
  className,
}: {
  title: string;
  headingId: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      aria-labelledby={headingId}
      className={[
        "rounded-lg border border-border bg-surface shadow-card p-4",
        className ?? "",
      ].join(" ")}
    >
      <h2 id={headingId} className="text-sm font-medium text-fg-subtle">
        {title}
      </h2>
      <div className="mt-2">{children}</div>
    </section>
  );
}

/**
 * Headline portfolio snapshot: total income, expenses, and net across all
 * properties for the selected year. Net loss is styled with the danger token
 * plus a textual "Loss" cue, mirroring the per-property IncomeExpenseTile.
 */
function PortfolioSnapshotTile({ summary }: { summary: DashboardSummary }) {
  const loss = isLoss(summary.net);
  const netLabel = loss ? "Net loss" : "Net income";
  return (
    <section
      aria-label={`Portfolio totals for ${summary.tax_year}`}
      className="rounded-lg border border-border bg-surface shadow-card p-4 sm:col-span-2"
    >
      <h2 className="text-sm font-medium text-fg-subtle">
        Portfolio snapshot ({summary.tax_year})
      </h2>
      <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div>
          <dt className="text-sm text-fg-muted">Total income</dt>
          <dd className="mt-1 text-2xl font-semibold tabular-nums text-fg">
            {formatMoney(summary.total_income)}
          </dd>
        </div>
        <div>
          <dt className="text-sm text-fg-muted">Total expenses</dt>
          <dd className="mt-1 text-2xl font-semibold tabular-nums text-fg">
            {formatMoney(summary.total_expenses)}
          </dd>
        </div>
        <div>
          <dt className="text-sm text-fg-muted">{netLabel}</dt>
          <dd
            className={[
              "mt-1 text-2xl font-semibold tabular-nums",
              loss ? "text-danger" : "text-success",
            ].join(" ")}
          >
            {formatMoney(summary.net)}
            {loss ? (
              <span className="ml-2 align-middle text-xs font-medium uppercase tracking-wide text-danger">
                Loss
              </span>
            ) : null}
          </dd>
        </div>
      </dl>
    </section>
  );
}

type CombinedState =
  | { status: "loading" }
  | { status: "loaded"; report: CombinedScheduleEReport }
  | { status: "error" };

/**
 * Combined Schedule E summary tile: portfolio income / expenses / net from the
 * combined report totals, plus the total annual depreciation (the sum of every
 * property's Line 18 total, summed exactly in integer cents via `sumMoney`).
 */
function CombinedScheduleETile({ combined }: { combined: CombinedState }) {
  return (
    <Tile title="Combined Schedule E" headingId="tile-combined">
      {combined.status === "loading" ? (
        <p className="text-sm text-fg-subtle" role="status">
          Loading Schedule E…
        </p>
      ) : combined.status === "error" ? (
        <p role="alert" className="text-sm text-danger">
          Could not load the combined Schedule E report.
        </p>
      ) : (
        <>
          <p className="text-xs text-fg-subtle">
            Portfolio Schedule E summary for {combined.report.tax_year}.
          </p>
          <dl className="mt-2 space-y-2">
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-sm text-fg-muted">Total income</dt>
              <dd className="tabular-nums font-semibold text-fg">
                {formatMoney(combined.report.totals.total_income)}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-sm text-fg-muted">Total expenses</dt>
              <dd className="tabular-nums font-semibold text-fg">
                {formatMoney(combined.report.totals.total_expenses)}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-sm text-fg-muted">Depreciation (Line 18)</dt>
              <dd className="tabular-nums font-semibold text-fg">
                {formatMoney(
                  sumMoney(combined.report.properties.map(depreciationOf)),
                )}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4 border-t border-border pt-2">
              <dt className="text-sm font-medium text-fg-muted">
                {isLoss(combined.report.totals.net) ? "Net loss" : "Net income"}
              </dt>
              <dd
                className={[
                  "tabular-nums text-lg font-semibold",
                  isLoss(combined.report.totals.net)
                    ? "text-danger"
                    : "text-success",
                ].join(" ")}
              >
                {formatMoney(combined.report.totals.net)}
                {isLoss(combined.report.totals.net) ? (
                  <span className="ml-2 align-middle text-xs font-medium uppercase tracking-wide text-danger">
                    Loss
                  </span>
                ) : null}
              </dd>
            </div>
          </dl>
        </>
      )}
    </Tile>
  );
}

/**
 * Depreciation-in-service tile: the total annual depreciation across the
 * portfolio (the same Line 18 sum) plus a count of properties with any
 * depreciation recorded this year.
 */
function DepreciationTile({ combined }: { combined: CombinedState }) {
  return (
    <Tile title="Depreciation in service" headingId="tile-depreciation">
      {combined.status === "loading" ? (
        <p className="text-sm text-fg-subtle" role="status">
          Loading…
        </p>
      ) : combined.status === "error" ? (
        <p role="alert" className="text-sm text-danger">
          Could not load depreciation.
        </p>
      ) : (
        (() => {
          const perProperty = combined.report.properties.map(depreciationOf);
          const total = sumMoney(perProperty);
          const withDepreciation = perProperty.filter(
            (value) => value !== "0.00",
          ).length;
          return (
            <>
              <p className="tabular-nums text-2xl font-semibold text-fg">
                {formatMoney(total)}
              </p>
              <p className="mt-1 text-xs text-fg-subtle">
                Annual depreciation across the portfolio (Schedule E Line 18).
              </p>
              <p className="mt-2 text-sm text-fg-muted">
                {withDepreciation}{" "}
                {withDepreciation === 1 ? "property" : "properties"} with
                depreciation this year.
              </p>
            </>
          );
        })()
      )}
    </Tile>
  );
}

/**
 * Needs-attention tile: lists properties whose income is still "0.00" for the
 * selected year (a nudge that year-end totals may not be recorded yet). When
 * every property has income, a positive confirmation is shown instead.
 */
function NeedsAttentionTile({
  properties,
}: {
  properties: readonly PropertySummary[];
}) {
  const zeroIncome = properties.filter(
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
            No income recorded yet this year:
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
 * Properties launchpad: a small per-property list of name + net for the year,
 * each linking to that property's page. Replaces the old breakdown table.
 */
function PropertiesLaunchpadTile({
  properties,
}: {
  properties: readonly PropertySummary[];
}) {
  return (
    <Tile
      title="Properties"
      headingId="tile-launchpad"
      className="sm:col-span-2"
    >
      <ul className="divide-y divide-border">
        {properties.map((property) => {
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
                {formatMoney(property.net)}
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
    <Link
      to={to}
      className="inline-flex rounded-md border border-border px-3 py-1.5 text-sm font-medium text-fg-muted hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      {label}
    </Link>
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
 * Dashboard page — a tiled "portfolio home" (Requirement 11).
 *
 * Renders, for a selected tax year, a responsive grid of numeric tiles: the
 * portfolio snapshot (totals + net income/loss), the combined Schedule E
 * summary and total depreciation, a needs-attention nudge for properties with
 * no recorded income, a per-property launchpad, and quick actions. A small
 * tax-year selector at the top drives every tile.
 *
 * Numbers, text, and links only — no charts, canvases, or visualizations. The
 * add-first-property empty state is shown when the user owns no properties
 * (Requirement 11.4).
 */
export default function DashboardPage({
  api = sharedApi,
  loadCombined = getCombinedReport,
  loadAssets = listAssets,
}: DashboardPageProps) {
  const currentYear = useMemo(() => new Date().getFullYear(), []);
  // The earliest depreciable-asset in-service year across all properties, or
  // null until assets load (or none exist). Sizes the tax-year selector so
  // older years are selectable for long-held properties.
  const [earliestYear, setEarliestYear] = useState<number | null>(null);
  const years = useMemo(() => taxYearRange(earliestYear), [earliestYear]);

  const [taxYear, setTaxYear] = useState<number>(currentYear);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [combined, setCombined] = useState<CombinedState>({
    status: "loading",
  });

  const loadDashboard = useCallback(
    async (year: number, signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const result = await api.getDashboard(year, signal);
        setSummary(result);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError("Could not load the dashboard.");
      } finally {
        setLoading(false);
      }
    },
    [api],
  );

  // (Re)load the dashboard summary whenever the selected tax year changes
  // (Requirement 11.3).
  useEffect(() => {
    const controller = new AbortController();
    void loadDashboard(taxYear, controller.signal);
    return () => controller.abort();
  }, [loadDashboard, taxYear]);

  // (Re)load the combined Schedule E report for the selected year; drives the
  // Schedule E and depreciation tiles.
  useEffect(() => {
    let active = true;
    setCombined({ status: "loading" });
    loadCombined(taxYear)
      .then((report) => {
        if (active) setCombined({ status: "loaded", report });
      })
      .catch(() => {
        if (active) setCombined({ status: "error" });
      });
    return () => {
      active = false;
    };
  }, [loadCombined, taxYear]);

  // Once the property list is known, fetch each property's assets (in parallel)
  // to find the earliest placed-in-service year across the whole portfolio,
  // which sizes the tax-year selector. Degrades to null (recent-years window)
  // on any failure. Runs on the property set, not the selected year.
  useEffect(() => {
    if (!summary || !summary.has_properties) return;
    let active = true;
    const ids = summary.properties.map((p) => p.property_id);
    Promise.all(
      ids.map((id) => loadAssets(id).catch(() => [] as DepreciableAsset[])),
    )
      .then((lists) => {
        if (!active) return;
        let earliest: number | null = null;
        for (const assets of lists) {
          for (const asset of assets) {
            const year = Number(asset.placed_in_service_date?.slice(0, 4));
            if (Number.isFinite(year) && year >= 1900) {
              earliest = earliest === null ? year : Math.min(earliest, year);
            }
          }
        }
        setEarliestYear(earliest);
      })
      .catch(() => {
        if (active) setEarliestYear(null);
      });
    return () => {
      active = false;
    };
  }, [summary, loadAssets]);

  return (
    <section aria-labelledby="page-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 id="page-heading" className="text-2xl font-semibold text-fg">
          Dashboard
        </h1>
        <TaxYearSelector value={taxYear} years={years} onChange={setTaxYear} />
      </div>

      <p className="mt-1 text-sm text-fg-subtle">
        Your portfolio at a glance for the selected tax year.
      </p>

      {error ? (
        <p role="alert" className="mt-4 text-sm text-danger">
          {error}
        </p>
      ) : null}

      {loading && !summary ? (
        <p className="mt-6 text-fg-muted">Loading dashboard…</p>
      ) : summary && !summary.has_properties ? (
        <DashboardEmptyState prompt={summary.empty_state_prompt} />
      ) : summary ? (
        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <PortfolioSnapshotTile summary={summary} />
          <CombinedScheduleETile combined={combined} />
          <DepreciationTile combined={combined} />
          <NeedsAttentionTile properties={summary.properties} />
          <PropertiesLaunchpadTile properties={summary.properties} />
          <QuickActionsTile />
        </div>
      ) : null}
    </section>
  );
}
