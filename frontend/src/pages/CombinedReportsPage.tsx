import { useState } from "react";
import { CombinedReportView } from "../components/reports/CombinedReportView";
import { Select, StateBlock } from "../components/ui";
import {
  getCombinedReport,
  type CombinedScheduleEReport,
} from "../api/reports";

interface CombinedReportsPageProps {
  /**
   * Injectable combined-report loader; defaults to the real
   * {@link getCombinedReport}. Tests supply a mocked implementation so the
   * page renders with no network access (Requirement 10, 16.2).
   */
  loadCombined?: (taxYear: number) => Promise<CombinedScheduleEReport>;
  /** Candidate tax years to offer in the selector. */
  years?: readonly number[];
}

/** Recent tax years, newest first, offered by default in the year selector. */
function defaultYears(): number[] {
  const current = new Date().getFullYear();
  const years: number[] = [];
  for (let year = current; year >= current - 6; year -= 1) {
    years.push(year);
  }
  return years;
}

/**
 * Portfolio-scope combined Schedule E report page (tasks 13.3 / 13.4,
 * Requirements 10, 16.2), routed at `/reports`.
 *
 * The user picks a tax year; on selection the combined, portfolio-level report
 * is fetched (no new endpoint — it reuses `GET /reports/combined`) and rendered
 * as a hand-off document via {@link CombinedReportView}: portfolio totals with
 * an emphasized net, then each property's Schedule E report. The page is
 * print-friendly (app chrome carries `print:hidden`; the tax-year control group
 * is hidden from print here, consistent with the per-property report page).
 *
 * Distinct from the per-property `ReportsPage` at
 * `/properties/:propertyId/reports`, which is unchanged.
 */
export default function CombinedReportsPage({
  loadCombined = getCombinedReport,
  years,
}: CombinedReportsPageProps = {}) {
  const yearOptions = years ?? defaultYears();

  const [taxYear, setTaxYear] = useState<number | null>(null);
  const [report, setReport] = useState<CombinedScheduleEReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleYearChange(value: string) {
    if (value === "") {
      setTaxYear(null);
      setReport(null);
      setError(null);
      return;
    }
    const year = Number(value);
    setTaxYear(year);
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const result = await loadCombined(year);
      setReport(result);
    } catch {
      setError("Unable to load the combined Schedule E report for this year.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <header>
        <h1 className="text-2xl font-semibold text-fg">Reports</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Combined Schedule E — a printable, portfolio-wide hand-off document.
          Select a tax year to roll every property's Schedule E report into one
          view with portfolio totals.
        </p>
      </header>

      <div className="mt-8 space-y-6">
        <section
          aria-labelledby="combined-report-controls-heading"
          className="print:hidden"
        >
          <h2 id="combined-report-controls-heading" className="sr-only">
            Report controls
          </h2>
          <div className="flex items-center gap-2">
            <label
              htmlFor="combined-report-tax-year"
              className="text-sm font-medium text-fg-muted"
            >
              Tax year
            </label>
            <Select
              id="combined-report-tax-year"
              value={taxYear === null ? "" : String(taxYear)}
              onChange={(event) => void handleYearChange(event.target.value)}
            >
              <option value="">Select a year…</option>
              {yearOptions.map((year) => (
                <option key={year} value={year}>
                  {year}
                </option>
              ))}
            </Select>
          </div>
        </section>

        {loading ? (
          <StateBlock kind="loading" title="Loading combined report…" />
        ) : error ? (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        ) : report ? (
          <CombinedReportView report={report} />
        ) : (
          <StateBlock
            kind="empty"
            title="No report yet"
            description="Choose a tax year above to generate the combined Schedule E report across all your properties."
          />
        )}
      </div>
    </>
  );
}
