import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { listAssets, type DepreciableAsset } from "../api/assets";
import { useMarkReportVisited } from "../lib/checklistStorage";
import { latestCompletedTaxYear, parseYearParam } from "../lib/taxYears";
import { usePropertyYearRange } from "../lib/usePropertyYearRange";
import { isAsyncLoading, useAsyncResource } from "../lib/useAsyncResource";
import { propertyPath } from "../components/navConfig";
import { EMPTY_COPY, IMPORT_LINK_LABEL } from "../lib/emptyCopy";
import { PageContainer } from "../components/PageContainer";
import { PropertySection } from "../components/PropertySection";
import { ReportView } from "../components/reports/ReportView";
import {
  Button,
  EmptyGuide,
  LoadingRegion,
  RefreshingIndicator,
  Select,
  StateBlock,
  TableSkeleton,
  TileSkeleton,
  useFirstLoad,
  useToast,
} from "../components/ui";
import { startDownload } from "../lib/packageJob";
import * as reportsApiDefault from "../api/reports";
import {
  reportToCsv,
  reportToJson,
  reportFilename,
  type PdfDownload,
  type ScheduleEReport,
} from "../api/reports";

/**
 * Subset of the reports API this page depends on. Injectable so tests can
 * supply a mocked implementation with no network access.
 */
export interface ReportsApi {
  getReport: (propertyId: string, taxYear: number) => Promise<ScheduleEReport>;
  /** Builds the Schedule E PDF; defaults to the real module function. */
  createReportPdf?: (propertyId: string, taxYear: number) => Promise<PdfDownload>;
}

interface ReportsPageProps {
  /** Injectable API layer; defaults to the real module (Requirement 10). */
  api?: ReportsApi;
  /** Candidate tax years to offer in the selector. */
  years?: readonly number[];
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
  useMarkReportVisited();
  const { propertyId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const reportsApiImpl: ReportsApi = api ?? reportsApiDefault;
  const { notify } = useToast();
  const [pdfBusy, setPdfBusy] = useState(false);

  // The property's depreciable assets size the selectable-year range: from the
  // earliest in-service year through the latest completed tax year (the current
  // year cannot be filed yet). An injected `years` prop overrides this for
  // tests.
  const [assets, setAssets] = useState<DepreciableAsset[]>([]);
  const derivedYears = usePropertyYearRange(propertyId, assets);
  const yearOptions = years ?? derivedYears;

  // Default the selected year to the latest completed tax year and auto-load
  // its report on mount, so the page lands on the latest filable year rather
  // than an empty prompt.
  const [taxYear, setTaxYear] = useState<number | null>(
    () => parseYearParam(searchParams.get("year")) ?? latestCompletedTaxYear(),
  );
  // A property switch clears the report; a tax-year change keeps the previous
  // report mounted while the new one loads (14.1-14.3). Clearing the year
  // disables loading.
  const {
    data: report,
    error,
    status,
    reload,
    setData: setReport,
  } = useAsyncResource(
    () => reportsApiImpl.getReport(propertyId, taxYear as number),
    {
      resetKeys: [propertyId],
      deps: [taxYear],
      enabled: propertyId !== "" && taxYear !== null,
      describeError: () => "Unable to load the Schedule E report for this year.",
    },
  );
  // Skeleton only before the first success for a property.
  const view = useFirstLoad({
    loading: isAsyncLoading(status),
    error,
    resetKey: propertyId,
  });
  // Load the property's assets to size the year range (active-flag guarded).
  useEffect(() => {
    if (!propertyId) return;
    let active = true;
    listAssets(propertyId)
      .then((loaded) => {
        if (active) setAssets(loaded);
      })
      .catch(() => {
        if (active) setAssets([]);
      });
    return () => {
      active = false;
    };
  }, [propertyId]);

  function handleYearChange(value: string) {
    if (value === "") {
      setTaxYear(null);
      setReport(null);
      return;
    }
    setTaxYear(Number(value));
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

  async function handleDownloadPdf() {
    if (!report || pdfBusy) return;
    setPdfBusy(true);
    try {
      const createPdf =
        reportsApiImpl.createReportPdf ?? reportsApiDefault.createReportPdf;
      const pdf = await createPdf(propertyId, report.header.tax_year);
      startDownload(pdf.download_url);
    } catch (err) {
      notify({
        variant: "error",
        title: "Could not create the PDF",
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setPdfBusy(false);
    }
  }

  return (
    <PageContainer>
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

            {view.showContent && report && (
              <div className="flex flex-wrap items-center gap-2 print:hidden">
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
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  loading={pdfBusy}
                  onClick={() => void handleDownloadPdf()}
                >
                  Download PDF
                </Button>
              </div>
            )}
          </div>
        </section>

        {view.showSkeleton ? (
          <LoadingRegion label="Loading report" className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-3">
              <TileSkeleton />
              <TileSkeleton />
              <TileSkeleton />
            </div>
            <TableSkeleton columns={3} />
          </LoadingRegion>
        ) : null}

        {view.showError ? (
          <StateBlock
            kind="error"
            compact={view.errorIsStale}
            title="Could not load the report"
            description={error ?? undefined}
            onRetry={
              taxYear !== null ? () => void reload() : undefined
            }
          />
        ) : null}

        {view.refreshing ? <RefreshingIndicator /> : null}

        {view.showContent ? (
          report ? (
            <ReportView report={report} />
          ) : (
            <EmptyGuide
              title={EMPTY_COPY.reports.title}
              description={EMPTY_COPY.reports.description}
              primary={{
                label: EMPTY_COPY.reports.primaryLabel,
                to: propertyPath(propertyId, "transactions"),
              }}
              secondary={{
                label: IMPORT_LINK_LABEL,
                to: "/imports/schedule-e",
              }}
            />
          )
        ) : null}
      </div>
    </PageContainer>
  );
}
