import { StateBlock, Tile } from "../ui";
import { formatMoney } from "../../lib/money";
import { depreciationTotal, type ReportState } from "./reportState";

/** Depreciation tile: the Line 18 total from the selected year's report. */
export function DepreciationTile({ report }: { report: ReportState }) {
  const total = depreciationTotal(report);
  return (
    <Tile title="Depreciation" headingId="tile-depreciation">
      {report.status === "loading" ? (
        <p className="text-sm text-fg-subtle" role="status">
          Loading…
        </p>
      ) : report.status === "error" ? (
        <StateBlock
          kind="error"
          compact
          title="Could not load the report"
          description={report.message}
        />
      ) : total !== null ? (
        <>
          <p className="tabular-nums text-2xl font-semibold text-fg">
            {formatMoney(total)}
          </p>
          <p className="mt-1 text-xs text-fg-subtle">
            Schedule E Line 18 for this tax year.
          </p>
        </>
      ) : null}
    </Tile>
  );
}
