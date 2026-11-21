import { DEPRECIATION_LINE, type ScheduleEReport } from "../../api/reports";
import type { AsyncResourceStatus } from "../../lib/useAsyncResource";

export type ReportState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "loaded"; report: ScheduleEReport }
  | { status: "error"; message: string };

/** Maps the async-resource snapshot for the Schedule E report to a tile state. */
export function toReportState(
  resourceStatus: AsyncResourceStatus,
  data: ScheduleEReport | null,
  error: string | null,
): ReportState {
  if (resourceStatus === "idle" && data === null) return { status: "idle" };
  if (data !== null) return { status: "loaded", report: data };
  if (error !== null) return { status: "error", message: error };
  return { status: "loading" };
}

/** Line 18 total of a loaded report ("0.00" when absent); null otherwise. */
export function depreciationTotal(report: ReportState): string | null {
  if (report.status !== "loaded") return null;
  return (
    report.report.lines.find((l) => l.line === DEPRECIATION_LINE)?.total ??
    "0.00"
  );
}
