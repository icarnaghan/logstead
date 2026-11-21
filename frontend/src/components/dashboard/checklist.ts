import type { TrendsSeries } from "../../api/dashboard";
import { toCents } from "../../lib/money";

/** Pure checklist derivation for the Dashboard Checklist_Card (Requirement 24). */

export type StepId = "property" | "transactions" | "loanOrAsset" | "report";

export interface ChecklistFlags {
  hasProperty: boolean;
  hasTransactions: boolean;
  hasLoanOrAsset: boolean;
  visitedReport: boolean;
}

export interface ChecklistView {
  steps: { id: StepId; done: boolean }[];
  completed: number;
  total: 4;
  visible: boolean;
}

export function computeChecklist(
  flags: ChecklistFlags,
  dismissed: boolean,
): ChecklistView {
  const steps: { id: StepId; done: boolean }[] = [
    { id: "property", done: flags.hasProperty },
    { id: "transactions", done: flags.hasTransactions },
    { id: "loanOrAsset", done: flags.hasLoanOrAsset },
    { id: "report", done: flags.visitedReport },
  ];
  const completed = steps.filter((s) => s.done).length;
  return { steps, completed, total: 4, visible: !dismissed && completed < 4 };
}

/** First incomplete step in the fixed order, or null when all are done. */
export function nextStep(view: ChecklistView): StepId | null {
  return view.steps.find((s) => !s.done)?.id ?? null;
}

const STEP_REASONS: Record<StepId, string> = {
  property: "Everything in Logstead is organized by property, so start here.",
  transactions:
    "Rent and expenses are what your Schedule E report is built from.",
  loanOrAsset:
    "Loan interest and depreciation are part of your yearly totals.",
  report: "Your Schedule E report brings the year's figures together.",
};

/** One-sentence reason shown under the next step. */
export function stepReason(id: StepId): string {
  return STEP_REASONS[id];
}

/** Progress text, e.g. "2 of 4 done" (Requirement 24.10). */
export function checklistProgressText(view: ChecklistView): string {
  return `${view.completed} of ${view.total} done`;
}

/** True when any year has non-zero income or expenses. */
export function hasTransactionData(trends: TrendsSeries): boolean {
  return trends.years.some(
    (y) => toCents(y.total_income) !== 0 || toCents(y.total_expenses) !== 0,
  );
}

/** True when any year has non-zero depreciation (step 3 shortcut). */
export function hasDepreciationData(trends: TrendsSeries): boolean {
  return trends.years.some((y) => toCents(y.depreciation_total) !== 0);
}
