/**
 * Chart data preparation — the Money_String → Integer_Cents boundary
 * (Requirements 13.1, 13.3, 16.3).
 *
 * Charts plot **integer cents**, never floating-point dollars. This module is
 * the single boundary where API money strings are converted, and it does so
 * exclusively through {@link toCents} so no float ever enters the chart
 * pipeline (Requirement 13.1, 13.3). Axis and tooltip formatters later render
 * `formatMoney(centsToMoney(cents))` (Requirement 13.2), keeping the inverse
 * exact.
 *
 * Each builder maps an API shape to a small, chart-ready datum array. The
 * expense-by-category builders additionally rank their output by descending
 * amount so the ranked bar chart reads top-to-bottom (Requirement 16.3).
 */

import { toCents } from "../../lib/money";
import type {
  CombinedScheduleEReport,
  ScheduleEReport,
} from "../../api/reports";
import type { PropertySummary } from "../../api/dashboard";
import type { ScheduleRow } from "../../api/assets";

/** One category slice for the expense-by-category chart (Req 16). */
export interface CategoryDatum {
  /** Human-readable category / line label. */
  label: string;
  /** Exact integer cents for this category. */
  cents: number;
}

/** One bar for the income vs. expenses vs. net chart (Req 17). */
export interface IncomeExpenseNetDatum {
  /** Which of the three portfolio figures this datum represents. */
  key: "Income" | "Expenses" | "Net";
  /** Exact integer cents; `Net` may be negative (a loss). */
  cents: number;
}

/** One bar for the net-by-property ranked chart (Req 18). */
export interface PropertyNetDatum {
  /** The property's display name. */
  label: string;
  /** Exact integer cents; negative denotes a loss. */
  cents: number;
}

/** One point on an asset depreciation schedule chart (Req 19). */
export interface DepreciationDatum {
  /** The tax year for this schedule row. */
  year: number;
  /** That year's depreciation, in exact integer cents. */
  amountCents: number;
  /** Basis remaining after that year, in exact integer cents. */
  remainingCents: number;
}

/**
 * Expense-by-category data for a single property's Schedule E report.
 *
 * Keeps only expense lines (`kind === "expense"`), converts each line total to
 * exact integer cents, and returns them **sorted by descending amount** so the
 * ranked bar chart reads largest-first (Requirement 16.3).
 */
export function expenseByCategory(report: ScheduleEReport): CategoryDatum[] {
  return report.lines
    .filter((line) => line.kind === "expense")
    .map((line) => ({ label: line.label, cents: toCents(line.total) }))
    .sort((a, b) => b.cents - a.cents);
}

/**
 * Expense-by-category data aggregated across every property in a combined
 * portfolio report. Expense lines are summed by label in exact integer cents,
 * then returned sorted by descending amount (Requirement 16.3).
 */
export function combinedExpenseByCategory(
  report: CombinedScheduleEReport,
): CategoryDatum[] {
  const totals = new Map<string, number>();
  for (const property of report.properties) {
    for (const line of property.lines) {
      if (line.kind !== "expense") continue;
      totals.set(line.label, (totals.get(line.label) ?? 0) + toCents(line.total));
    }
  }
  return [...totals.entries()]
    .map(([label, cents]) => ({ label, cents }))
    .sort((a, b) => b.cents - a.cents);
}

/**
 * Income / expenses / net bars from a totals object (portfolio or property).
 * Returns the three bars in a fixed, readable order (Requirement 17).
 */
export function incomeExpenseNet(totals: {
  total_income: string;
  total_expenses: string;
  net: string;
}): IncomeExpenseNetDatum[] {
  return [
    { key: "Income", cents: toCents(totals.total_income) },
    { key: "Expenses", cents: toCents(totals.total_expenses) },
    { key: "Net", cents: toCents(totals.net) },
  ];
}

/**
 * Net-by-property ranked bars from the dashboard per-property breakdown.
 * Converts each property's net to exact integer cents and ranks descending so
 * the strongest performers read first (Requirement 18).
 */
export function netByProperty(
  properties: readonly PropertySummary[],
): PropertyNetDatum[] {
  return properties
    .map((property) => ({
      label: property.property_name,
      cents: toCents(property.net),
    }))
    .sort((a, b) => b.cents - a.cents);
}

/**
 * Depreciation-schedule series from an asset's computed schedule rows. Each
 * row's amount and remaining basis are converted to exact integer cents
 * (Requirement 19); the year is carried through unchanged.
 */
export function depreciationSeries(
  rows: readonly ScheduleRow[],
): DepreciationDatum[] {
  return rows.map((row) => ({
    year: row.tax_year,
    amountCents: toCents(row.amount),
    remainingCents: toCents(row.remaining_basis),
  }));
}
