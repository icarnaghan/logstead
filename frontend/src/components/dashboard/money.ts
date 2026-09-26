/**
 * Money helpers for the dashboard UI.
 *
 * Money is a fixed two-decimal **string** across the API (Requirement 13.3),
 * so the UI never converts amounts to JavaScript numbers for storage. These
 * helpers only inspect and format for display; they perform no arithmetic.
 *
 * A net figure may be negative — a two-decimal string like "-125.00" — which
 * denotes a loss (Requirement 11.1). The formatter renders losses clearly with
 * a leading minus sign, and {@link isLoss} lets callers add a textual "loss"
 * cue for screen-reader users rather than relying on the sign alone.
 */

/** True when a money string represents a negative amount (a loss). */
export function isLoss(amount: string): boolean {
  const value = Number(amount);
  return Number.isFinite(value) && value < 0;
}

/**
 * Parse a two-decimal money string to an exact integer number of cents.
 *
 * Works purely on the string form (sign, dollars, cents digits) so no floating
 * point is involved and no precision is lost. Cent digits shorter/longer than
 * two are padded/truncated defensively, though the API contract is always two.
 * Returns 0 for input that is not a recognizable money string.
 */
function toCents(amount: string): number {
  const match = /^(-)?(\d+)(?:\.(\d+))?$/.exec(amount.trim());
  if (!match) return 0;
  const sign = match[1] ? -1 : 1;
  const dollars = match[2];
  const cents = (match[3] ?? "").padEnd(2, "0").slice(0, 2);
  return sign * (Number(dollars) * 100 + Number(cents));
}

/** Format an exact integer number of cents back to a two-decimal string. */
function centsToMoney(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  const dollars = Math.floor(abs / 100);
  const remainder = String(abs % 100).padStart(2, "0");
  return `${sign}${dollars}.${remainder}`;
}

/**
 * Sum a list of two-decimal money strings **exactly**, returning a two-decimal
 * string. Arithmetic is performed in integer cents (never floating point), so
 * results carry no rounding error. An empty list sums to "0.00"; negatives
 * (losses) are supported.
 */
export function sumMoney(amounts: readonly string[]): string {
  const total = amounts.reduce((acc, amount) => acc + toCents(amount), 0);
  return centsToMoney(total);
}

/**
 * Format a money string for display as US currency, e.g. "1250.00" →
 * "$1,250.00" and "-125.00" → "-$125.00". Falls back to the raw input when it
 * is not a finite number.
 */
export function formatMoney(amount: string): string {
  const value = Number(amount);
  if (!Number.isFinite(value)) return amount;
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
  });
}
