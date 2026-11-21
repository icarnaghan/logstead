import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CombinedReportView } from "../components/reports/CombinedReportView";
import {
  Button,
  EmptyGuide,
  LoadingRegion,
  PageHeader,
  RefreshingIndicator,
  Select,
  StateBlock,
  TableSkeleton,
  TileSkeleton,
  useFirstLoad,
  useToast,
} from "../components/ui";
import { propertyPath } from "../components/navConfig";
import { useShellProperties } from "../components/ShellPropertiesContext";
import { EMPTY_COPY, IMPORT_LINK_LABEL } from "../lib/emptyCopy";
import { startDownload } from "../lib/packageJob";
import { useMarkReportVisited } from "../lib/checklistStorage";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { latestCompletedTaxYear, parseYearParam } from "../lib/taxYears";
import { usePortfolioYearRange } from "../lib/usePortfolioYearRange";
import { isAsyncLoading, useAsyncResource } from "../lib/useAsyncResource";
import {
  createCombinedReportPdf,
  getCombinedReport,
  type CombinedScheduleEReport,
  type PdfDownload,
} from "../api/reports";

interface CombinedReportsPageProps {
  /**
   * Injectable combined-report loader; defaults to the real
   * {@link getCombinedReport}. Tests supply a mocked implementation so the
   * page renders with no network access (Requirement 10, 16.2).
   */
  loadCombined?: (taxYear: number) => Promise<CombinedScheduleEReport>;
  /** Injectable combined PDF builder; defaults to the real API call. */
  createPdf?: (taxYear: number) => Promise<PdfDownload>;
  /** Candidate tax years to offer in the selector. */
  years?: readonly number[];
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
  createPdf = (taxYear: number) => createCombinedReportPdf(taxYear),
  years,
}: CombinedReportsPageProps = {}) {
  useDocumentTitle("Reports");
  useMarkReportVisited();
  const { notify } = useToast();
  const [searchParams] = useSearchParams();
  const [pdfBusy, setPdfBusy] = useState(false);
  const { properties: shellProperties } = useShellProperties();
  const firstProperty = shellProperties[0];
  // The selectable years run from the earliest activity across every property
  // through the latest completed tax year. An injected `years` prop overrides
  // them for tests.
  const portfolioYears = usePortfolioYearRange();
  const yearOptions = years ?? portfolioYears;

  // Default to the latest completed tax year (or the first injected year) and
  // load its report on mount, so the page lands on a report rather than an
  // empty prompt. Choosing the blank option still clears the selection.
  const [taxYear, setTaxYear] = useState<number | null>(
    () =>
      parseYearParam(searchParams.get("year")) ??
      years?.[0] ??
      latestCompletedTaxYear(),
  );
  // A tax-year change keeps the prior report mounted while the new one loads
  // (Requirements 14.1-14.3); clearing the year disables loading.
  const {
    data: report,
    error,
    status,
    reload,
    setData: setReport,
  } = useAsyncResource(() => loadCombined(taxYear as number), {
    deps: [taxYear],
    enabled: taxYear !== null,
    describeError: () =>
      "Unable to load the combined Schedule E report for this year.",
  });
  // Skeleton only before the first success.
  const view = useFirstLoad({ loading: isAsyncLoading(status), error });
  function handleYearChange(value: string) {
    if (value === "") {
      setTaxYear(null);
      setReport(null);
      return;
    }
    setTaxYear(Number(value));
  }
  async function handleDownloadPdf() {
    if (taxYear === null || pdfBusy) return;
    setPdfBusy(true);
    try {
      const pdf = await createPdf(taxYear);
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
    <>
      <PageHeader
        title="Reports"
        description="Combined Schedule E — a printable, portfolio-wide hand-off document. Select a tax year to roll every property's Schedule E report into one view with portfolio totals."
      />

      <div className="mt-8 space-y-6">
        <section
          aria-labelledby="combined-report-controls-heading"
          className="print:hidden"
        >
          <h2 id="combined-report-controls-heading" className="sr-only">
            Report controls
          </h2>
          <div className="flex flex-wrap items-center gap-4">
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
              onChange={(event) => handleYearChange(event.target.value)}
            >
              <option value="">Select a year…</option>
              {yearOptions.map((year) => (
                <option key={year} value={year}>
                  {year}
                </option>
              ))}
            </Select>
          </div>
          {report ? (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              loading={pdfBusy}
              onClick={() => void handleDownloadPdf()}
            >
              Download PDF
            </Button>
          ) : null}
          <Link
            to="/accountant-package"
            className="text-sm font-medium text-accent underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Prepare an accountant package
          </Link>
          </div>
        </section>

        {view.showSkeleton ? (
          <LoadingRegion label="Loading combined report" className="space-y-4">
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
            title="Could not load the combined report"
            description={error ?? undefined}
            onRetry={taxYear !== null ? () => void reload() : undefined}
          />
        ) : null}

        {view.refreshing ? <RefreshingIndicator /> : null}

        {view.showContent ? (
          report ? (
            <CombinedReportView report={report} />
          ) : (
            <EmptyGuide
              title={EMPTY_COPY.combinedReports.title}
              description={EMPTY_COPY.combinedReports.description}
              primary={{
                label: EMPTY_COPY.combinedReports.primaryLabel,
                to: firstProperty
                  ? propertyPath(firstProperty.id, "transactions")
                  : "/properties",
              }}
              secondary={{
                label: IMPORT_LINK_LABEL,
                to: "/imports/schedule-e",
              }}
            />
          )
        ) : null}
      </div>
    </>
  );
}
