/**
 * Money helpers for the transactions UI.
 *
 * Money is a fixed two-decimal **string** across the API (Requirement 13.3),
 * so the UI never converts amounts to JavaScript numbers for storage. These
 * helpers only validate and format for display; they do not perform arithmetic.
 */

/** A value is a well-formed positive money string like "0.01", "1250", "99.9". */
export function isPositiveAmount(raw: string): boolean {
  const trimmed = raw.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) return false;
  // Reject zero (and "0.00") — amounts must be > 0 (Requirement 5.2).
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

/** Format a money string for display as US currency, e.g. "1250.00" → "$1,250.00". */
export function formatMoney(amount: string): string {
  const value = Number(amount);
  if (Number.isNaN(value)) return amount;
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
  });
}
