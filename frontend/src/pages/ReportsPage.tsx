import { useState } from "react";
import { useParams } from "react-router-dom";
import { PropertySection } from "../components/PropertySection";
import { ReportView } from "../components/reports/ReportView";
import { Button, Select, StateBlock } from "../components/ui";
import * as reportsApiDefault from "../api/reports";
import {
  reportToCsv,
  reportToJson,
  reportFilename,
  type ScheduleEReport,
} from "../api/reports";

/**
 * Subset of the reports API this page depends on. Injectable so tests can
 * supply a mocked implementation with no network access.
 */
export interface ReportsApi {
  getReport: (propertyId: string, taxYear: number) => Promise<ScheduleEReport>;
}

interface ReportsPageProps {
  /** Injectable API layer; defaults to the real module (Requirement 10). */
  api?: ReportsApi;
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
 * Triggers a browser download of `content` as a file named `filename` with the
 * given MIME type, using a Blob + object URL. Kept as a module function so it
 * is easy to exercise/spy in tests.
 */
function downloadFile(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/**
 * Per-property Schedule E report page (task 24.1, Requirement 10).
 *
 * The user picks a tax year; on selection the report is fetched and rendered as
 * numbers-and-forms (header with usage days, per-line income/expense totals,
 * Line 18 depreciation, itemized Line 19 "Other", and total income / expenses /
 * net where a negative net is shown as a loss) — no charts. Download buttons
 * serialize the already-fetched report to CSV or JSON client-side and trigger a
 * browser download (Requirement 10.7).
 */
export default function ReportsPage({ api, years }: ReportsPageProps = {}) {
  const { propertyId = "" } = useParams();
  const reportsApiImpl: ReportsApi = api ?? reportsApiDefault;
  const yearOptions = years ?? defaultYears();

  const [taxYear, setTaxYear] = useState<number | null>(null);
  const [report, setReport] = useState<ScheduleEReport | null>(null);
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
      const result = await reportsApiImpl.getReport(propertyId, year);
      setReport(result);
    } catch {
      setError("Unable to load the Schedule E report for this year.");
    } finally {
      setLoading(false);
    }
  }

  function handleDownloadCsv() {
    if (!report) return;
    downloadFile(
      reportToCsv(report),
      reportFilename(report, "csv"),
      "text/csv",
    );
  }

  function handleDownloadJson() {
    if (!report) return;
    downloadFile(
      reportToJson(report),
      reportFilename(report, "json"),
      "application/json",
    );
  }

  return (
    <>
      <PropertySection
        propertyId={propertyId}
        title="Schedule E Report"
        description="Select a tax year to view this property's Schedule E report as numeric line totals — no charts. Export the report as CSV or JSON."
      />

      <div className="mt-8 space-y-6">
        <section
          aria-labelledby="report-controls-heading"
          className="print:hidden"
        >
          <h2 id="report-controls-heading" className="sr-only">
            Report controls
          </h2>
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex items-center gap-2">
              <label
                htmlFor="report-tax-year"
                className="text-sm font-medium text-fg-muted"
              >
                Tax year
              </label>
              <Select
                id="report-tax-year"
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

            {report && (
              <div className="flex items-center gap-2 print:hidden">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={handleDownloadCsv}
                >
                  Download CSV
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={handleDownloadJson}
                >
                  Download JSON
                </Button>
              </div>
            )}
          </div>
        </section>

        {loading ? (
          <StateBlock kind="loading" title="Loading report…" />
        ) : error ? (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        ) : report ? (
          <ReportView report={report} />
        ) : (
          <StateBlock
            kind="empty"
            title="No report yet"
            description="Choose a tax year above to generate this property's Schedule E report."
          />
        )}
      </div>
    </>
  );
}
