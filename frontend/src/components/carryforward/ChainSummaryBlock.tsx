import { useId } from "react";
import type { ChainSummary } from "../../lib/carryforwardChain";
import { formatMoneyWholeDollars } from "../../lib/money";
import {
  continuationSentence,
  firstBreakSentence,
  furtherBreakText,
  totalGapSentence,
} from "./carryforwardText";

/**
 * "Where the chain breaks" summary shown above the table when at least one
 * year is a mismatch. All content is derived from existing series fields; the
 * meaning is carried by text, not color.
 */
export function ChainSummaryBlock({
  summary,
  tolerance,
}: {
  summary: ChainSummary;
  tolerance: string;
}) {
  const headingId = useId();
  const first = summary.firstBreak;
  const further = summary.furtherBreaks;
  return (
    <section
      aria-labelledby={headingId}
      className="space-y-2 rounded-md border border-border bg-surface-muted px-4 py-3 text-sm text-fg"
    >
      <h2 id={headingId} className="font-medium">
        Where the chain breaks
      </h2>
      <p>{firstBreakSentence(first)}</p>
      {first.endYear > first.startYear ? <p>{continuationSentence(first)}</p> : null}
      {further.length > 0 ? (
        <>
          <p>Further breaks:</p>
          <ul className="list-disc pl-5">
            {further.map((b) => (
              <li key={b.startYear}>{furtherBreakText(b)}</li>
            ))}
          </ul>
        </>
      ) : null}
      <p>{totalGapSentence(summary.totalGap, tolerance)}</p>
      <p>
        Check the return for each break year; this summary is a reconciliation
        aid, not tax advice.
      </p>
    </section>
  );
}

/**
 * Explains the whole-dollar tolerance (Requirements 6.1-6.4). Rendered with the
 * reconciliation table only, using the wire `status_tolerance` Money_String.
 */
export function ToleranceNote({ tolerance }: { tolerance: string }) {
  return (
    <p className="text-sm text-fg-muted">
      Matches within {formatMoneyWholeDollars(tolerance)} count as OK because
      returns are filed in whole dollars.
    </p>
  );
}
