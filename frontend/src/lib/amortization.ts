/**
 * Client-side loan projection preview (Requirements 10.4, 10.5, 10.6).
 *
 * Mirrors the backend engine (`compute_payment_rows`) for a balance-anchored
 * Loan. All money is integer cents (`BigInt`) and the annual rate is an
 * integer scaled by 10^4, so interest is exact integer arithmetic: there is
 * no `number` arithmetic on money or the rate.
 *
 * Payment `k` (k >= 1) is dated `anchorDate` plus `k` calendar months,
 * clamped from the original anchor day. The payment made on the anchor date
 * is already applied to `anchorBalance` and is not part of the projection.
 */

const MAX_MONEY_CENTS = 99_999_999_999n; // 999,999,999.99
const MAX_RATE_SCALED = 1_000_000n; // 100.0000 at 4 dp
const MAX_PAYMENTS = 600;
const MIN_YEAR = 1900;
const MAX_YEAR = 9999;
const RATE_DIVISOR = 12_000_000n; // 12 months * 100 percent * 10^4 scale

export interface LoanProjectionInput {
  anchorBalance: string;
  annualInterestRate: string;
  monthlyPayment: string;
  extraPrincipal?: string;
  anchorDate: string;
  payoffDate?: string;
}

export interface LoanProjection {
  remainingPayments: number;
  nextPaymentDate: string;
  /** Date of the final row when the balance reaches 0.00, else null. */
  projectedPayoffDate: string | null;
  /** Balance left at `payoffDate` (two decimals), else null. */
  payoffBalance: string | null;
  /** Amount of the final row when the balance reaches 0.00, else null. */
  finalPayment: string | null;
  /** Sum of row interest, two decimals. */
  totalInterest: string;
}

/** Parse a non-negative decimal string with at most `maxDp` decimals, scaled by 10^maxDp. */
function parseScaled(raw: unknown, maxDp: number): bigint | null {
  if (typeof raw !== "string") return null;
  const match = new RegExp(`^(\\d+)(?:\\.(\\d{1,${maxDp}}))?$`).exec(raw.trim());
  if (!match) return null;
  return BigInt(match[1] + (match[2] ?? "").padEnd(maxDp, "0"));
}

function isLeap(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

function daysInMonth(year: number, month: number): number {
  if (month === 2) return isLeap(year) ? 29 : 28;
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

interface YMD {
  year: number;
  month: number;
  day: number;
}

/** Strict `YYYY-MM-DD` parse of a real calendar date. */
function parseDate(raw: unknown): YMD | null {
  if (typeof raw !== "string") return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (year < 1 || month < 1 || month > 12) return null;
  if (day < 1 || day > daysInMonth(year, month)) return null;
  return { year, month, day };
}

function formatDate({ year, month, day }: YMD): string {
  const p = (n: number, w: number) => String(n).padStart(w, "0");
  return `${p(year, 4)}-${p(month, 2)}-${p(day, 2)}`;
}

/** Date of payment `index` (>= 1) months after `anchor`, clamped from the anchor day. */
function paymentDate(anchor: YMD, index: number): YMD {
  const m0 = anchor.month - 1 + index;
  const year = anchor.year + Math.floor(m0 / 12);
  const month = (m0 % 12) + 1;
  return { year, month, day: Math.min(anchor.day, daysInMonth(year, month)) };
}

/** Half-up cents of `balance * rate / 1200` (rate scaled by 10^4). */
function interestCents(balanceCents: bigint, rateScaled: bigint): bigint {
  return (2n * balanceCents * rateScaled + 12_000_000n) / (2n * RATE_DIVISOR);
}

/** Render integer cents as a two-decimal string. */
function centsToString(cents: bigint): string {
  const digits = cents.toString().padStart(3, "0");
  return `${digits.slice(0, -2)}.${digits.slice(-2)}`;
}

function parseMoney(raw: unknown, allowZero: boolean): bigint | null {
  const cents = parseScaled(raw, 2);
  if (cents === null || cents > MAX_MONEY_CENTS) return null;
  if (!allowZero && cents === 0n) return null;
  return cents;
}

/**
 * Project the remaining payments of an anchored Loan. Returns `null` for any
 * missing or invalid input, a payment that does not exceed the first month's
 * interest, a schedule needing more than 600 payments, a date past year 9999,
 * or a payoff date before the next payment date.
 */
export function projectLoan(input: LoanProjectionInput): LoanProjection | null {
  const balance0 = parseMoney(input.anchorBalance, false);
  const payment = parseMoney(input.monthlyPayment, false);
  const extraRaw = input.extraPrincipal?.trim() ?? "";
  const extra = extraRaw === "" ? 0n : parseMoney(extraRaw, true);
  const rate = parseScaled(input.annualInterestRate, 4);
  const anchor = parseDate(input.anchorDate);
  if (balance0 === null || payment === null || extra === null || rate === null || anchor === null) {
    return null;
  }
  if (rate > MAX_RATE_SCALED || anchor.year < MIN_YEAR || anchor.year > MAX_YEAR) return null;

  const payoffRaw = input.payoffDate;
  let payoff: YMD | null = null;
  if (payoffRaw !== undefined && payoffRaw !== "") {
    payoff = parseDate(payoffRaw);
    if (payoff === null) return null;
  }

  // The payment must exceed one month of interest on the anchor balance.
  if (payment <= interestCents(balance0, rate)) return null;

  const next = paymentDate(anchor, 1);
  if (next.year > MAX_YEAR) return null;
  const nextIso = formatDate(next);
  if (payoff !== null && formatDate(payoff) < nextIso) return null;
  const payoffIso = payoff === null ? null : formatDate(payoff);

  const due = payment + extra;
  let balance = balance0;
  let totalInterest = 0n;
  let rows = 0;
  let lastDate = nextIso;
  let lastAmount = 0n;

  for (let k = 1; ; k += 1) {
    const d = paymentDate(anchor, k);
    if (d.year > MAX_YEAR) return null;
    const iso = formatDate(d);
    if (payoffIso !== null && iso > payoffIso) break;
    if (k > MAX_PAYMENTS) return null;

    const interest = interestCents(balance, rate);
    rows = k;
    lastDate = iso;
    totalInterest += interest;
    if (balance + interest <= due) {
      lastAmount = balance + interest;
      balance = 0n;
      break;
    }
    lastAmount = due;
    balance -= due - interest;
  }

  const paidOff = balance === 0n;
  return {
    remainingPayments: rows,
    nextPaymentDate: nextIso,
    projectedPayoffDate: paidOff ? lastDate : null,
    payoffBalance: !paidOff ? centsToString(balance) : null,
    finalPayment: paidOff ? centsToString(lastAmount) : null,
    totalInterest: centsToString(totalInterest),
  };
}
