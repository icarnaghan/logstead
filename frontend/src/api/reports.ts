/**
 * Schedule E reports API module.
 *
 * Wraps the shared {@link apiClient} with a typed helper for the per-property
 * Schedule E report endpoint (Requirement 10). Money values are exchanged as
 * two-decimal strings, matching the backend's `Decimal`-as-string convention;
 * this module never coerces them to `number` so no precision is lost in the UI
 * layer (Requirement 13.3).
 *
 * Backend route (task 16.1):
 *  - GET /properties/{propertyId}/report?taxYear=<year>
 *
 * The backend serializes the report dataclass verbatim, so each line row's
 * total is exposed under the `total` field (not `amount`) and money values are
 * plain two-decimal strings.
 *
 * There is no server-side export route in the current handler route table, so
 * exporting is performed client-side by serializing the already-fetched report
 * (see {@link reportToJson} / {@link reportToCsv}).
 */

import { apiClient, type ApiClient } from "../lib/apiClient";

/** Whether a Schedule E line contributes to total income or total expenses. */
export type ReportLineKind = "income" | "expense";

/** A single Schedule E line total on a report (Requirement 10.1). */
export interface ReportLine {
  /** The Schedule E Part I line number. */
  line: number;
  /** Human-readable line label. */
  label: string;
  /** Whether this line rolls up into income or expenses. */
  kind: ReportLineKind;
  /** Two-decimal money string for the line total, e.g. "1250.00". */
  total: string;
}

/** One itemized Line 19 "Other" expense (Requirement 10.5). */
export interface OtherItem {
  description: string;
  /** Two-decimal money string, e.g. "42.00". */
  amount: string;
}

/** The Schedule E report header for a property + tax year (Requirement 10.2). */
export interface ReportHeader {
  property_id: string;
  property_name: string;
  address: string;
  property_type: string | null;
  tax_year: number;
  fair_rental_days: number;
  personal_use_days: number;
}

/** Income / expense / net totals (Requirement 10.4). Net may be negative (a loss). */
export interface ReportTotals {
  /** Two-decimal money string. */
  total_income: string;
  /** Two-decimal money string (includes Line 18 depreciation). */
  total_expenses: string;
  /** Two-decimal money string; negative denotes a loss. */
  net: string;
}

/** A per-property Schedule E report (Requirements 10.1-10.5). */
export interface ScheduleEReport {
  header: ReportHeader;
  lines: ReportLine[];
  other_items: OtherItem[];
  totals: ReportTotals;
}

/**
 * The combined, portfolio-level Schedule E report for a tax year.
 *
 * Mirrors the backend `GET /reports/combined?taxYear=<year>` shape: one
 * {@link ScheduleEReport} per property plus the rolled-up portfolio
 * {@link ReportTotals}. Money remains two-decimal strings end-to-end.
 */
export interface CombinedScheduleEReport {
  tax_year: number;
  properties: ScheduleEReport[];
  totals: ReportTotals;
}

/** The Schedule E Part I line number for depreciation. */
export const DEPRECIATION_LINE = 18;
/** The Schedule E Part I line number for itemized "Other" expenses. */
export const OTHER_LINE = 19;

function reportPath(propertyId: string): string {
  return `/properties/${encodeURIComponent(propertyId)}/report`;
}

/**
 * Fetches the combined, portfolio-level Schedule E report for a tax year.
 *
 * Wraps `GET /reports/combined?taxYear=<year>`; the backend rolls every
 * property's Schedule E report into one payload with portfolio totals.
 */
export function getCombinedReport(
  taxYear: number,
  client: ApiClient = apiClient,
): Promise<CombinedScheduleEReport> {
  return client.get<CombinedScheduleEReport>("/reports/combined", {
    query: { taxYear },
  });
}

/**
 * Fetches the Schedule E report for a property and tax year (Requirement 10.1).
 */
export function getReport(
  propertyId: string,
  taxYear: number,
  client: ApiClient = apiClient,
): Promise<ScheduleEReport> {
  return client.get<ScheduleEReport>(reportPath(propertyId), {
    query: { taxYear },
  });
}

/**
 * Serialize a fetched report to pretty-printed JSON (Requirement 10.7). The
 * money strings are preserved verbatim so the exported file carries exact
 * two-decimal precision.
 */
export function reportToJson(report: ScheduleEReport): string {
  return JSON.stringify(report, null, 2);
}

/** Escape a value for inclusion in a CSV field (RFC 4180 quoting). */
function csvField(value: string | number): string {
  const text = String(value);
  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function csvRow(values: (string | number)[]): string {
  return values.map(csvField).join(",");
}

/**
 * Serialize a fetched report to a Schedule E CSV table (Requirement 10.7).
 *
 * The layout mirrors the backend's own CSV export: a header block, the line
 * totals (line number, label, income/expense kind, amount), the itemized
 * Line 19 "Other" list, and the income/expense/net totals. Money renders as
 * the verbatim two-decimal strings.
 */
export function reportToCsv(report: ScheduleEReport): string {
  const { header, lines, other_items, totals } = report;
  const rows: string[] = [];

  rows.push(csvRow(["Property", header.property_name]));
  rows.push(csvRow(["Address", header.address]));
  rows.push(csvRow(["Property Type", header.property_type ?? ""]));
  rows.push(csvRow(["Tax Year", header.tax_year]));
  rows.push(csvRow(["Fair Rental Days", header.fair_rental_days]));
  rows.push(csvRow(["Personal Use Days", header.personal_use_days]));
  rows.push("");

  rows.push(csvRow(["Line", "Label", "Kind", "Amount"]));
  for (const line of lines) {
    rows.push(csvRow([line.line, line.label, line.kind, line.total]));
  }
  rows.push("");

  rows.push(csvRow(["Other (Line 19) Itemization"]));
  rows.push(csvRow(["Description", "Amount"]));
  for (const item of other_items) {
    rows.push(csvRow([item.description, item.amount]));
  }
  rows.push("");

  rows.push(csvRow(["Total Income", totals.total_income]));
  rows.push(csvRow(["Total Expenses", totals.total_expenses]));
  rows.push(csvRow(["Net", totals.net]));

  return rows.join("\n");
}

/** Suggested download filename for an exported report of the given format. */
export function reportFilename(
  report: ScheduleEReport,
  format: "csv" | "json",
): string {
  const name = report.header.property_name
    .replace(/[^a-z0-9]+/gi, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase();
  const base = name.length > 0 ? name : "property";
  return `schedule-e-${base}-${report.header.tax_year}.${format}`;
}
