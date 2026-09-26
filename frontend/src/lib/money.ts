/**
 * Canonical money helpers for the entire frontend (Requirements 7.1, 7.4, 13.1, 13.3).
 *
 * Money is a fixed two-decimal **string** across the API (Requirement 13.3),
 * so the UI never converts amounts to JavaScript numbers for storage or
 * arithmetic. All math in this module is performed in exact integer cents —
 * there is **no floating-point arithmetic** anywhere in the money pipeline.
 *
 * This module consolidates the three formatters that previously lived in
 * `components/transactions/money.ts`, `components/dashboard/money.ts`, and the
 * inline formatter in `components/properties/PropertyDetailsView.tsx` into one
 * canonical superset (Requirement 7.4). It exports:
 *
 * - {@link formatMoney}     — display a money string as US currency.
 * - {@link isLoss}          — is a money string negative (a loss)?
 * - {@link isPositiveAmount}— input-validation guard for amount fields.
 * - {@link toMoneyString}   — normalize a valid input to two decimals.
 * - {@link sumMoney}        — exact integer-cents sum of many money strings.
 * - {@link toCents}         — parse a money string to exact integer cents.
 * - {@link centsToMoney}    — render exact integer cents back to a money string.
 *
 * A net figure may be negative — a two-decimal string like "-125.00" — which
 * denotes a loss. {@link formatMoney} renders losses clearly with a leading
 * minus sign, and {@link isLoss} lets callers add a textual "loss" cue for
 * screen-reader users rather than relying on the sign (color) alone.
 */

/**
 * Parse a two-decimal money string to an exact integer number of cents.
 *
 * Works purely on the string form (sign, dollars, cents digits) so no floating
 * point is involved and no precision is lost (Requirement 13.1, 13.3). Cent
 * digits shorter/longer than two are padded/truncated defensively, though the
 * API contract is always two. Surrounding whitespace is tolerated. Returns `0`
 * for input that is not a recognizable money string.
 *
 * Exported because the chart layer converts money strings to integer cents at
 * the data-preparation boundary (Requirement 13.1).
 */
export function toCents(amount: string): number {
  const match = /^(-)?(\d+)(?:\.(\d+))?$/.exec(amount.trim());
  if (!match) return 0;
  const sign = match[1] ? -1 : 1;
  const dollars = match[2];
  const cents = (match[3] ?? "").padEnd(2, "0").slice(0, 2);
  return sign * (Number(dollars) * 100 + Number(cents));
}

/**
 * Format an exact integer number of cents back to a two-decimal string, e.g.
 * `125000` → "1250.00" and `-12550` → "-125.50". The inverse of
 * {@link toCents} for well-formed money strings.
 */
export function centsToMoney(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  const dollars = Math.floor(abs / 100);
  const remainder = String(abs % 100).padStart(2, "0");
  return `${sign}${dollars}.${remainder}`;
}

/** True when a money string represents a negative amount (a loss). */
export function isLoss(amount: string): boolean {
  const value = Number(amount);
  return Number.isFinite(value) && value < 0;
}

/**
 * A value is a well-formed **positive** money string like "0.01", "1250",
 * "99.9". Used to validate amount inputs before submission — zero (and "0.00")
 * is rejected because amounts must be greater than zero.
 */
export function isPositiveAmount(raw: string): boolean {
  const trimmed = raw.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) return false;
  // Reject zero (and "0.00") — amounts must be > 0.
  return Number(trimmed) > 0;
}

/**
 * Normalize a valid money input to a fixed two-decimal string for the API,
 * e.g. "1250" → "1250.00", "99.9" → "99.90". Returns the trimmed input
 * unchanged when it is not a well-formed amount (validation surfaces the error
 * separately).
 */
export function toMoneyString(raw: string): string {
  const trimmed = raw.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) return trimmed;
  const [whole, frac = ""] = trimmed.split(".");
  return `${whole}.${frac.padEnd(2, "0")}`;
}

/**
 * Sum a list of two-decimal money strings **exactly**, returning a two-decimal
 * string. Arithmetic is performed in integer cents (never floating point), so
 * results carry no rounding error. An empty list sums to "0.00"; negatives
 * (losses) are supported. Unparseable entries contribute zero.
 */
export function sumMoney(amounts: readonly string[]): string {
  const total = amounts.reduce((acc, amount) => acc + toCents(amount), 0);
  return centsToMoney(total);
}

/**
 * Format a money string for display as US currency, e.g. "1250.00" →
 * "$1,250.00" and "-125.00" → "-$125.00".
 *
 * Behavior for the merged superset (Requirement 7.4):
 * - Empty string, `null`, or `undefined` → "" (callers render nothing).
 * - Non-numeric input → passed through unchanged (never throws).
 * - Otherwise formatted with the `en-US` USD locale.
 *
 * Values are rendered through `tabular-nums` at every call site to preserve the
 * existing numeric alignment (Requirement 7.5).
 */
export function formatMoney(amount: string | null | undefined): string {
  if (amount === null || amount === undefined || amount === "") return "";
  const value = Number(amount);
  if (!Number.isFinite(value)) return amount;
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
  });
}
