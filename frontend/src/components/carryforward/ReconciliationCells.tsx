import type { ReconciledYear } from "../../api/carryforward";
import { formatMoneyWholeDollars, isLoss } from "../../lib/money";
import { driftText, STATUS_LABEL } from "./carryforwardText";

/**
 * Render a Schedule E net with the app's existing loss convention
 * (Requirement 5.4): a negative net is styled with the danger token and
 * carries a textual "loss" cue so the meaning does not rest on color alone
 * (mirrors the dashboard's net rendering via {@link formatMoneyWholeDollars}/{@link isLoss}).
 */
export function ScheduleENetCell({ net }: { net: string }) {
  const loss = isLoss(net);
  return (
    <span
      className={[
        "tabular-nums",
        loss ? "text-danger" : "text-fg",
      ].join(" ")}
    >
      {formatMoneyWholeDollars(net)}
      {loss ? (
        <span className="ml-1 text-xs font-medium uppercase tracking-wide text-danger">
          {" "}
          (loss)
        </span>
      ) : null}
    </span>
  );
}

/**
 * Status cell for a reconciled year (Requirements 4.5, 5.2). Renders the
 * textual {@link STATUS_LABEL}; a `mismatch` year is additionally emphasized
 * with the danger token so a problem year stands out — but the textual label
 * ("Needs review") carries the distinction on its own, never color alone.
 */
export function StatusCell({
  status,
  carriedFromYear,
  hint,
  carriedHint,
}: {
  status: ReconciledYear["status"];
  carriedFromYear: number | null;
  hint?: string | null;
  carriedHint?: string | null;
}) {
  const mismatch = status === "mismatch";
  // A `carried` year names its root-cause year when known; it uses the neutral
  // muted style, never the danger style reserved for `mismatch`.
  const label =
    status === "carried" && carriedFromYear !== null
      ? `Carried from ${carriedFromYear}`
      : STATUS_LABEL[status];
  return (
    <div className="flex flex-col gap-0.5">
      <span
        className={[
          "text-sm",
          mismatch ? "font-semibold text-danger" : "text-fg-muted",
        ].join(" ")}
      >
        {label}
      </span>
      {hint ? <span className="text-xs text-fg-muted">{hint}</span> : null}
      {carriedHint ? (
        <span className="text-xs text-fg-muted">{carriedHint}</span>
      ) : null}
    </div>
  );
}

/**
 * Drift cell (Requirements 7.2-7.6, 10.4): see {@link driftText}. Null
 * (unreported) shows an em dash.
 */
export function DriftCell({ drift }: { drift: string | null }) {
  if (drift === null) {
    return <span className="text-fg-muted">—</span>;
  }
  return <span className="tabular-nums text-fg">{driftText(drift)}</span>;
}
