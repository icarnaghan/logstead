import type { ReconciledYear } from "../../api/carryforward";
import { ApiError } from "../../lib/apiClient";
import {
  carriedBreakInfo,
  type ChainBreak,
  type ChainSummary,
} from "../../lib/carryforwardChain";
import {
  centsToMoney,
  formatMoneyWholeDollars,
  toCents,
} from "../../lib/money";

/**
 * Human-readable status label for a reconciled year (Requirement 4.5). The
 * label is textual so the distinction never rests on color alone: `mismatch`
 * years read "Needs review", `ok` years read "OK", and `unreported` years read
 * "Not reported".
 */
export const STATUS_LABEL: Record<ReconciledYear["status"], string> = {
  ok: "OK",
  mismatch: "Needs review",
  carried: "Carried from earlier year",
  unreported: "Not reported",
};

/**
 * True when `raw` is a non-negative two-decimal money amount (Requirements 3.3,
 * 7.3). Zero and "0.00" are accepted — a suspended-loss carryforward and an
 * opening balance may legitimately be 0.00. Up to two fractional digits are
 * allowed; the value must parse as >= 0.
 */
export function isNonNegativeAmount(raw: string): boolean {
  const trimmed = raw.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) return false;
  return Number(trimmed) >= 0;
}

/**
 * Extract the server-side validation message for the `amount` field from a
 * rejected save (Requirements 3.3, 5.5, 7.3). A 400 carries `{ field, message }`
 * in its body; when the offending field is `amount` the field message is used,
 * otherwise the error's own message is surfaced. Non-ApiError failures fall
 * back to a generic message.
 */
export function amountErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 400) {
      const body = err.body as { field?: string; message?: string } | null;
      if (body?.field === "amount" && body.message) return body.message;
      if (body?.message) return body.message;
    }
    return err.message;
  }
  return fallback;
}

/**
 * Extract the server-side validation message for one of `fields` from a
 * rejected save (Requirements 5.5, 6.5). Generalizes {@link amountErrorMessage}
 * so the allowed-loss control can surface the backend's 400 error whether the
 * offending field is reported as `allowed_loss` or `allowedLoss` (and likewise
 * `fully_allowed` / `fullyAllowed`): when the offending field is one of
 * `fields` the field message is used, otherwise the error's own message is
 * surfaced. Non-ApiError failures fall back to a generic message.
 */
export function fieldErrorMessage(
  err: unknown,
  fields: readonly string[],
  fallback: string,
): string {
  if (err instanceof ApiError) {
    if (err.status === 400) {
      const body = err.body as { field?: string; message?: string } | null;
      if (body?.field && fields.includes(body.field) && body.message) {
        return body.message;
      }
      if (body?.message) return body.message;
    }
    return err.message;
  }
  return fallback;
}

/**
 * Hint line for a `mismatch` row, computed from the previous row in the series
 * (Requirements 5.1-5.6). Returns null for every other status. The first row
 * compares with the opening balance; an unreported previous year falls back to
 * the expected figure; otherwise the hint states what the prior return carried
 * out versus what this year's line shows, and names the lines to check.
 */
export function mismatchHint(
  year: ReconciledYear,
  previous: ReconciledYear | undefined,
): string | null {
  if (year.status !== "mismatch") return null;
  if (!previous) return "Compared with your opening balance.";
  if (previous.reported_carryforward === null) {
    return `The ${previous.tax_year} return is not reported, so this was compared with the expected figure only.`;
  }
  // formatMoneyWholeDollars works on the Money_String text, so no float math.
  const prior = previous.tax_year;
  const carriedOut = formatMoneyWholeDollars(previous.expected_carryforward);
  const reported = formatMoneyWholeDollars(year.reported_carryforward ?? "0.00");
  return `The ${prior} return carried out about ${carriedOut}, but this return's line shows ${reported}. Check this year's Form 8582 line and the ${prior} return's carry-out.`;
}

/** Absolute value of a Money_String, via exact integer cents (no floats). */
function absMoney(amount: string): string {
  return centsToMoney(Math.abs(toCents(amount)));
}

/** Whole-dollar display of the magnitude of a Money_String. */
function absDollars(amount: string): string {
  return formatMoneyWholeDollars(absMoney(amount));
}

/**
 * Describe a signed Break_Amount: negative "dropped", positive "extra", zero
 * "no net change". Returns the phrase that follows "about" context, e.g.
 * "$902 dropped".
 */
function describeAmount(amount: string): string {
  const cents = toCents(amount);
  if (cents === 0) return "no net change";
  return `about ${absDollars(amount)} ${cents < 0 ? "dropped" : "extra"}`;
}

export function firstBreakSentence(b: ChainBreak): string {
  if (b.priorYear !== null && b.priorCarryOut !== null) {
    return `The chain first breaks in ${b.startYear}: the ${b.priorYear} return carried out about ${formatMoneyWholeDollars(b.priorCarryOut)}, but the ${b.startYear} line shows ${formatMoneyWholeDollars(b.reported)}.`;
  }
  return `The chain first breaks in ${b.startYear}: the ${b.startYear} line shows ${formatMoneyWholeDollars(b.reported)}, where about ${formatMoneyWholeDollars(b.expectedCarryIn)} was expected.`;
}

export function continuationSentence(b: ChainBreak): string {
  if (toCents(b.endAmount) === 0) {
    return `The mismatch continues through ${b.endYear}, with no net change in total.`;
  }
  const cents = toCents(b.endAmount);
  return `The mismatch continues through ${b.endYear}, where about ${absDollars(b.endAmount)} appears ${cents < 0 ? "dropped" : "extra"} in total.`;
}

export function furtherBreakText(b: ChainBreak): string {
  const years =
    b.endYear > b.startYear ? `${b.startYear} to ${b.endYear}` : `${b.startYear}`;
  return `${years}: ${describeAmount(b.endAmount)}.`;
}

export function totalGapSentence(
  gap: ChainSummary["totalGap"],
  tolerance: string,
): string {
  const cents = toCents(gap.drift);
  if (Math.abs(cents) <= toCents(tolerance)) {
    return `As of ${gap.year}, the reported line is within ${formatMoneyWholeDollars(tolerance)} of the expected carry-in.`;
  }
  return `As of ${gap.year}, the reported line is about ${absDollars(gap.drift)} ${cents < 0 ? "under" : "over"} the expected carry-in.`;
}

/** Hint for a `carried` row pointing back at the break it inherited. */
export function carriedHintText(
  year: ReconciledYear,
  chain: ChainSummary | null,
): string | null {
  const info = carriedBreakInfo(year, chain);
  if (info === null) return null;
  const direction = toCents(info.drift) < 0 ? "under" : "over";
  const base = `Inherits the ${info.breakYear} break: this line is about ${absDollars(info.drift)} ${direction} the expected carry-in.`;
  return info.firstBreakYear !== null
    ? `${base} The chain first broke in ${info.firstBreakYear}.`
    : base;
}

/**
 * Text for a non-null drift value (Requirements 7.2-7.6, 10.4): `reported -
 * expected` in whole dollars with a textual direction cue so meaning never
 * rests on color. The sign and zero-ness come from the Money_String text itself
 * (no float arithmetic): positive reads "+$X over", negative reads "-$X under",
 * zero shows just the formatted value.
 */
export function driftText(drift: string): string {
  const text = drift.trim();
  const negative = text.startsWith("-");
  const zero = !/[1-9]/.test(text);
  const formatted = formatMoneyWholeDollars(text);
  if (zero) return formatted;
  if (negative) {
    // formatMoneyWholeDollars drops the minus when the magnitude rounds to $0
    // (e.g. "-0.01"), so guarantee the sign cue (Requirement 7.4).
    const signed = formatted.startsWith("-") ? formatted : `-${formatted}`;
    return `${signed} under`;
  }
  return `+${formatted} over`;
}
