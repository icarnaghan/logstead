/**
 * Pure derivation of "where the carryforward chain breaks" from the
 * reconciliation series the carryforward page already holds.
 *
 * Nothing here touches React, the DOM or the network. Every money amount is a
 * fixed two-decimal string; all arithmetic is exact integer-cent subtraction
 * via {@link toCents} / {@link centsToMoney}, so there is no floating-point
 * arithmetic on money. Inputs are never mutated.
 */

import type { ReconciledYear } from "../api/carryforward";
import { centsToMoney, toCents } from "./money";

/** One maximal run of consecutive `mismatch` rows. */
export interface ChainBreak {
  /** First mismatch year of the run (the break year). */
  readonly startYear: number;
  /** Last mismatch year of the run; equals startYear for a single year. */
  readonly endYear: number;
  /** Signed Money_String: drift(start) - baseline drift. Negative = dropped. */
  readonly startAmount: string;
  /** Signed Money_String: drift(end) - baseline drift. Negative = dropped. */
  readonly endAmount: string;
  /** The start row's reported line (Money_String). */
  readonly reported: string;
  /** The start row's expected carry-in (Money_String). */
  readonly expectedCarryIn: string;
  /**
   * The preceding row's year and expected carry-out when that row exists and
   * has a reported value; both null for the first row or an unreported prior
   * row (callers then compare with the expected carry-in only).
   */
  readonly priorYear: number | null;
  readonly priorCarryOut: string | null;
}

/** The derived reading of a whole series. */
export interface ChainSummary {
  readonly firstBreak: ChainBreak;
  /** Later runs, ascending by startYear. Empty when there is one run. */
  readonly furtherBreaks: readonly ChainBreak[];
  /** Latest row with a non-null drift. */
  readonly totalGap: { readonly year: number; readonly drift: string };
}

/** Mutable working state for a run while it is being built. */
interface OpenRun {
  startYear: number;
  endYear: number;
  baselineCents: number;
  startAmount: string;
  endAmount: string;
  reported: string;
  expectedCarryIn: string;
  priorYear: number | null;
  priorCarryOut: string | null;
}

/**
 * Group consecutive `mismatch` rows of an ascending series into breaks and
 * report the total gap.
 *
 * Run grouping: a run starts at a `mismatch` row that follows a non-mismatch
 * row (or the series start) and ends at the last consecutive `mismatch` row.
 * Any non-mismatch row, including an unreported one, closes the run.
 *
 * Baseline rule: a run's baseline is the `drift` (in cents) of the nearest
 * earlier row with a non-null drift, or 0 when none exists. A break amount is
 * `drift(row) - baseline`, so a later break reports only the change it caused.
 * A `mismatch` row with a null drift (malformed) counts as `0.00`.
 *
 * Returns `null` when no row is `mismatch`. Does not mutate `years`.
 */
export function summarizeChainBreaks(
  years: readonly ReconciledYear[],
): ChainSummary | null {
  const runs: ChainBreak[] = [];
  let open: OpenRun | null = null;
  let lastDriftCents = 0;
  let totalGap: { year: number; drift: string } | null = null;

  const close = (): void => {
    if (open === null) return;
    runs.push({
      startYear: open.startYear,
      endYear: open.endYear,
      startAmount: open.startAmount,
      endAmount: open.endAmount,
      reported: open.reported,
      expectedCarryIn: open.expectedCarryIn,
      priorYear: open.priorYear,
      priorCarryOut: open.priorCarryOut,
    });
    open = null;
  };

  years.forEach((row, index) => {
    if (row.status === "mismatch") {
      const driftCents = row.drift === null ? 0 : toCents(row.drift);
      if (open === null) {
        const prev = index > 0 ? years[index - 1] : undefined;
        const prevReported =
          prev !== undefined && prev.reported_carryforward !== null;
        const amount = centsToMoney(driftCents - lastDriftCents);
        open = {
          startYear: row.tax_year,
          endYear: row.tax_year,
          baselineCents: lastDriftCents,
          startAmount: amount,
          endAmount: amount,
          reported: row.reported_carryforward ?? "0.00",
          expectedCarryIn: row.expected_carry_in,
          priorYear: prevReported ? prev.tax_year : null,
          priorCarryOut: prevReported ? prev.expected_carryforward : null,
        };
      } else {
        open.endYear = row.tax_year;
        open.endAmount = centsToMoney(driftCents - open.baselineCents);
      }
    } else {
      close();
    }

    if (row.drift !== null) {
      lastDriftCents = toCents(row.drift);
      totalGap = { year: row.tax_year, drift: row.drift };
    }
  });
  close();

  if (runs.length === 0 || totalGap === null) return null;
  return {
    firstBreak: runs[0],
    furtherBreaks: runs.slice(1),
    totalGap,
  };
}

/** What a `carried` row inherited. */
export interface CarriedBreakInfo {
  /** The row's `carried_from_year`. */
  readonly breakYear: number;
  /** The row's own drift (Money_String). */
  readonly drift: string;
  /** The first break year when it differs from `breakYear`, else null. */
  readonly firstBreakYear: number | null;
}

/**
 * Hint data for a `carried` row, or `null` unless the row is `carried` with a
 * non-null `carried_from_year` and `drift`. `firstBreakYear` is set only when
 * the chain's first break differs from the row's own break year.
 */
export function carriedBreakInfo(
  year: ReconciledYear,
  summary: ChainSummary | null,
): CarriedBreakInfo | null {
  if (
    year.status !== "carried" ||
    year.carried_from_year === null ||
    year.drift === null
  ) {
    return null;
  }
  const firstYear = summary?.firstBreak.startYear ?? null;
  return {
    breakYear: year.carried_from_year,
    drift: year.drift,
    firstBreakYear:
      firstYear !== null && firstYear !== year.carried_from_year
        ? firstYear
        : null,
  };
}
