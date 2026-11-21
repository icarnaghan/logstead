/**
 * Pure integer-cents helpers for the itemized-expenses page (Requirements 9.1,
 * 9.2, 9.3, 14.2). All arithmetic goes through `toCents` / `centsToMoney` in
 * `lib/money.ts`; there is no floating-point math.
 */
import { centsToMoney, formatMoney, toCents } from "./money";

/**
 * Whether the "Update total to $X (itemized)" action is shown (Requirement 9.1,
 * 9.2, 9.8 handled by the caller disabling for multi-row totals).
 *
 * Visible only when an entered total exists, at least one itemized entry
 * exists, and the itemized sum differs from the entered total.
 */
export function syncVisible(
  enteredTotal: string | null | undefined,
  itemizedSum: string,
  itemizedCount: number,
): boolean {
  if (enteredTotal === null || enteredTotal === undefined || enteredTotal === "") {
    return false;
  }
  if (itemizedCount <= 0) return false;
  return toCents(enteredTotal) !== toCents(itemizedSum);
}

/** Sync button label, e.g. "Update total to $3,100.00 (itemized)". */
export function syncLabel(itemizedSum: string): string {
  return `Update total to ${formatMoney(centsToMoney(toCents(itemizedSum)))} (itemized)`;
}

/** Signed difference `itemized - entered` in exact integer cents. */
export function deltaCents(enteredTotal: string, itemizedSum: string): number {
  return toCents(itemizedSum) - toCents(enteredTotal);
}

/** Format signed cents as a money string with an explicit sign, e.g. "+$5.00". */
function signedMoney(cents: number): string {
  const formatted = formatMoney(centsToMoney(cents));
  return cents > 0 ? `+${formatted}` : formatted;
}

export interface ChangeDescriptionInput {
  /** Display name of the category, e.g. "Repairs". */
  label: string;
  /** Schedule E line number, e.g. 14. */
  line: number;
  taxYear: number;
  enteredTotal: string;
  itemizedSum: string;
  itemizedCount: number;
}

/**
 * Exact-change sentence for the sync confirm dialog (Requirement 9.3): line
 * number, tax year, current total, new total, and signed difference.
 */
export function describeChange(input: ChangeDescriptionInput): string {
  const { label, line, taxYear, enteredTotal, itemizedSum, itemizedCount } = input;
  const from = formatMoney(centsToMoney(toCents(enteredTotal)));
  const to = formatMoney(centsToMoney(toCents(itemizedSum)));
  const diff = signedMoney(deltaCents(enteredTotal, itemizedSum));
  const noun = itemizedCount === 1 ? "entry" : "entries";
  return (
    `Update the ${label} total for ${taxYear}? ` +
    `Schedule E line ${line} for ${taxYear} will change from ${from} to ${to} (${diff}). ` +
    `Your entered total becomes the sum of your ${itemizedCount} itemized ${noun}.`
  );
}
