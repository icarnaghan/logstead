import type { ReconciledYear } from "../../api/carryforward";
import type { ChainSummary } from "../../lib/carryforwardChain";
import { formatMoneyWholeDollars, isLoss } from "../../lib/money";
import { AllowedLossControl } from "./AllowedLossControl";
import { carriedHintText, mismatchHint } from "./carryforwardText";
import {
  DriftCell,
  ScheduleENetCell,
  StatusCell,
} from "./ReconciliationCells";
import { ReportedEditor } from "./ReportedEditor";

interface RowActions {
  onSave: (taxYear: number, amount: string) => Promise<void>;
  onClear: (taxYear: number) => Promise<void>;
  onSetAllowed: (taxYear: number, amount: string) => Promise<void>;
  onClearAllowed: (taxYear: number) => Promise<void>;
  onSetFullyAllowed: (taxYear: number, on: boolean) => Promise<void>;
}

/**
 * One reconciliation row (Requirements 4.6, 5.1, 5.2, 5.5, 5.6). Shows the
 * four-digit year, the Schedule E net (with loss styling), the
 * Expected_Carryforward, an inline editor for the Reported_Carryforward, and
 * the textual status. A `mismatch` row is highlighted distinctly and, because
 * the expected and reported figures are their own columns, both remain visible
 * on that row so the user can see the discrepancy.
 */
function ReconciliationRow({
  year,
  hint,
  carriedHint,
  onSave,
  onClear,
  onSetAllowed,
  onClearAllowed,
  onSetFullyAllowed,
}: RowActions & {
  year: ReconciledYear;
  hint: string | null;
  carriedHint: string | null;
}) {
  const mismatch = year.status === "mismatch";
  return (
    <tr
      className={[
        "border-b border-border",
        mismatch ? "bg-danger-subtle" : undefined,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <td className="py-2 pr-4 tabular-nums text-fg">{year.tax_year}</td>
      <td className="py-2 pr-4 text-right">
        <ScheduleENetCell net={year.schedule_e_net} />
      </td>
      <td className="py-2 pr-4 text-right tabular-nums text-fg">
        {formatMoneyWholeDollars(year.expected_carry_in)}
      </td>
      <td className="py-2 pr-4 text-right align-top tabular-nums">
        <ReportedEditor year={year} onSave={onSave} onClear={onClear} />
      </td>
      <td className="py-2 pr-4 text-right align-top tabular-nums">
        <DriftCell drift={year.drift} />
      </td>
      <td className="py-2 pr-4 text-right align-top tabular-nums">
        {isLoss(year.schedule_e_net) ? (
          <AllowedLossControl
            year={year}
            onSetAllowed={onSetAllowed}
            onClearAllowed={onClearAllowed}
            onSetFullyAllowed={onSetFullyAllowed}
          />
        ) : null}
      </td>
      <td className="py-2 pr-4 text-right align-top tabular-nums text-fg">
        {formatMoneyWholeDollars(year.expected_carryforward)}
      </td>
      <td className="py-2 pr-4 align-top">
        <StatusCell
          status={year.status}
          carriedFromYear={year.carried_from_year}
          hint={hint}
          carriedHint={carriedHint}
        />
      </td>
    </tr>
  );
}

/**
 * The reconciliation table (Requirement 5.1, 5.2): one row per `years` entry in
 * ascending chronological order (the backend returns them ascending). Columns:
 * Year, Schedule E net, Expected carryforward, Reported carryforward, Drift,
 * Allowed loss, Status. The Allowed loss cell carries the {@link AllowedLossControl} on
 * loss rows and is empty on non-loss rows, so every row has the same cell count.
 */
export function ReconciliationTable({
  years,
  chain,
  onSave,
  onClear,
  onSetAllowed,
  onClearAllowed,
  onSetFullyAllowed,
}: RowActions & {
  years: readonly ReconciledYear[];
  chain: ChainSummary | null;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">
          Passive loss carryforward reconciliation by tax year
        </caption>
        <thead>
          <tr className="border-b border-border text-left text-fg-subtle">
            <th scope="col" className="py-2 pr-4 font-medium">
              Year
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              Schedule E net
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              Expected entering year
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              Prior years' unallowed losses (Form 8582)
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              Drift
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              Allowed loss
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              Expected to carry out
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              Status
            </th>
          </tr>
        </thead>
        <tbody>
          {years.map((year, index) => (
            <ReconciliationRow
              key={year.tax_year}
              year={year}
              hint={mismatchHint(year, years[index - 1])}
              carriedHint={carriedHintText(year, chain)}
              onSave={onSave}
              onClear={onClear}
              onSetAllowed={onSetAllowed}
              onClearAllowed={onClearAllowed}
              onSetFullyAllowed={onSetFullyAllowed}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
