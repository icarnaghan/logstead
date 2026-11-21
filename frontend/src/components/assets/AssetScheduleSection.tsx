import { lazy } from "react";
import { StateBlock } from "../ui";
import type { DepreciableAsset, ScheduleRow } from "../../api/assets";
import { ChartCard } from "../charts/ChartCard";
import { LazyChart } from "../charts/LazyChart";
import { depreciationSeries } from "../charts/prepare";
import { ScheduleTable } from "./ScheduleTable";

/**
 * The depreciation-schedule chart is the lazy boundary: Recharts is reached only
 * through this `React.lazy` import, so it code-splits into its own async chunk
 * absent from the initial paint (Requirement 14). The always-present schedule
 * data table (`ScheduleTable`) is Recharts-free and imported eagerly above.
 */
const DepreciationChart = lazy(() => import("../charts/DepreciationChart"));

/** Expanded asset's year-by-year depreciation schedule (chart + editable table). */
export function AssetScheduleSection({
  asset,
  schedule,
  loading,
  error,
  overrideErrors,
  overrideGeneralError,
  onRetry,
  onOverrideChange,
}: {
  asset: DepreciableAsset;
  schedule: ScheduleRow[];
  loading: boolean;
  error: string | null;
  overrideErrors: Record<string, string>;
  overrideGeneralError: string | null;
  onRetry: (assetId: string) => void | Promise<void>;
  onOverrideChange: (taxYear: number, amount: string | null) => Promise<void>;
}) {
  return (
    <section
      aria-labelledby="schedule-heading"
      className="rounded-lg border border-border bg-surface p-4 shadow-card"
    >
      <h3 id="schedule-heading" className="text-base font-semibold text-fg">
        Depreciation schedule: {asset.description}
      </h3>
      {loading ? (
        <p className="mt-2 text-sm text-fg-muted">Loading schedule…</p>
      ) : error ? (
        <div className="mt-2">
          <StateBlock
            kind="error"
            compact
            title={error}
            onRetry={() => onRetry(asset.id)}
          />
        </div>
      ) : schedule.length > 0 ? (
        <div className="mt-3">
          {overrideGeneralError && (
            <p role="alert" className="mb-2 text-sm text-danger">
              {overrideGeneralError}
            </p>
          )}
          <ChartCard
            title="Depreciation & remaining basis"
            ariaLabel={`Year-by-year depreciation and remaining basis for ${asset.description}`}
            chart={
              <LazyChart
                fallbackTable={
                  <ScheduleTable
                    caption={`Year-by-year depreciation schedule for ${asset.description}`}
                    rows={schedule}
                    overrides={asset.depreciation_overrides ?? {}}
                  />
                }
              >
                <DepreciationChart data={depreciationSeries(schedule)} />
              </LazyChart>
            }
            // The visible data table is the single editable override
            // editor; the lazy chart's fallback table above stays
            // read-only so there is never a second live editor for
            // the same asset.
            dataTable={
              <ScheduleTable
                caption={`Year-by-year depreciation schedule for ${asset.description}`}
                rows={schedule}
                editable
                overrides={asset.depreciation_overrides ?? {}}
                onOverrideChange={onOverrideChange}
                overrideErrors={overrideErrors}
              />
            }
          />
        </div>
      ) : (
        <ScheduleTable
          caption={`Year-by-year depreciation schedule for ${asset.description}`}
          rows={schedule}
          overrides={asset.depreciation_overrides ?? {}}
        />
      )}
    </section>
  );
}
