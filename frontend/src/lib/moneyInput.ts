/**
 * Pure helpers for the MoneyInput primitive (Requirement 12).
 *
 * Canonical text is what forms store: an optional leading "-" (only when
 * negatives are allowed), digits, and at most one "." followed by at most two
 * digits, i.e. it always matches `^-?\d*(\.\d{0,2})?$`. No floating point is
 * involved; everything is string manipulation.
 */

export interface MoneyInputOptions {
  allowNegative?: boolean;
}

/**
 * Reduce arbitrary text (typed or pasted) to canonical money text. Currency
 * symbols, thousands separators, letters and whitespace are dropped; only the
 * first "." is kept; decimals are cut to two digits; a leading "-" survives
 * only when `allowNegative` is true. Idempotent.
 */
export function sanitizeMoneyInput(
  raw: string,
  opts: MoneyInputOptions = {},
): string {
  const { allowNegative = false } = opts;
  const compact = raw.replace(/[^\d.-]/g, "");
  const negative = allowNegative && compact.startsWith("-");
  const body = compact.replace(/-/g, "");
  const dot = body.indexOf(".");
  let result: string;
  if (dot === -1) {
    result = body;
  } else {
    const intPart = body.slice(0, dot);
    const frac = body.slice(dot + 1).replace(/\./g, "").slice(0, 2);
    result = `${intPart}.${frac}`;
  }
  return negative ? `-${result}` : result;
}

/**
 * Two-decimal display with thousands separators:
 * "1250.5" -> "1,250.50", "-3" -> "-3.00", "" (or no digits) -> "".
 */
export function formatMoneyDisplay(canonical: string): string {
  const clean = sanitizeMoneyInput(canonical, { allowNegative: true });
  if (!/\d/.test(clean)) return "";
  const negative = clean.startsWith("-");
  const unsigned = negative ? clean.slice(1) : clean;
  const [intRaw = "", fracRaw = ""] = unsigned.split(".");
  const intDigits = intRaw.replace(/^0+(?=\d)/, "") || "0";
  const grouped = intDigits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const frac = fracRaw.padEnd(2, "0");
  return `${negative ? "-" : ""}${grouped}.${frac}`;
}

/**
 * Inverse of {@link formatMoneyDisplay}: strips separators and returns
 * canonical text, so `parseMoneyDisplay(formatMoneyDisplay(c))` is the
 * two-decimal canonical form of `c`.
 */
export function parseMoneyDisplay(
  display: string,
  opts: MoneyInputOptions = {},
): string {
  return sanitizeMoneyInput(display, opts);
}
