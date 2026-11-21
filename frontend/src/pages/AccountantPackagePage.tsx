import { useEffect, useState } from "react";
import {
  PackageContentsList,
  PackageDisclaimer,
  PackageStatusPanel,
  PropertyPicker,
} from "../components/accountant-package";
import {
  usePackageJob,
  type UsePackageJobOptions,
} from "../components/accountant-package/usePackageJob";
import {
  Button,
  ConfirmDialog,
  PageHeader,
  Select,
  StateBlock,
  useFirstLoad,
} from "../components/ui";
import { listProperties, type Property } from "../api/properties";
import { isTerminal } from "../lib/packageJob";
import { latestCompletedTaxYear } from "../lib/taxYears";
import { useAsyncResource } from "../lib/useAsyncResource";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { usePortfolioYearRange } from "../lib/usePortfolioYearRange";

interface AccountantPackagePageProps {
  /** Injected job API and poll interval (test seam). */
  jobOptions?: UsePackageJobOptions;
  /** Injected properties loader (test seam). */
  loadProperties?: (signal?: AbortSignal) => Promise<readonly Property[]>;
}

/**
 * Accountant package page (Requirement 17). The user picks a tax year and the
 * properties to include, prepares a ZIP in the background, and downloads it.
 * The page holds no figures and gives no tax advice.
 */
export default function AccountantPackagePage({
  jobOptions,
  loadProperties = listProperties,
}: AccountantPackagePageProps = {}) {
  useDocumentTitle("Accountant package");
  const years = usePortfolioYearRange();
  const [taxYear, setTaxYear] = useState<number>(latestCompletedTaxYear());
  const yearOptions = years.includes(taxYear)
    ? years
    : [...years, taxYear].sort((a, b) => b - a);

  const { data: properties } = useAsyncResource(
    (signal) => loadProperties(signal),
    { describeError: () => "Unable to load your properties." },
  );
  const allProperties = properties ?? [];
  // null means "every property is checked", the default.
  const [picked, setPicked] = useState<string[] | null>(null);
  const selectedIds = picked ?? allProperties.map((p) => p.id);

  const { job, error, busy, start, remove, refresh } =
    usePackageJob(jobOptions);
  const view = useFirstLoad({ loading: busy, error });
  const active = job !== null && !isTerminal(job.status);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Download links expire; reload the job to get a fresh one (Requirement 17.8).
  const expiresIn = job?.status === "complete" ? job.download_expires_in_seconds : null;
  const jobId = job?.id;
  useEffect(() => {
    if (jobId === undefined || expiresIn === null) return;
    const timer = setTimeout(() => void refresh(), expiresIn * 1000);
    return () => clearTimeout(timer);
  }, [jobId, expiresIn, refresh]);

  const prepare = () => void start(taxYear, selectedIds);

  async function confirmDelete() {
    setDeleting(true);
    try {
      await remove();
    } finally {
      setDeleting(false);
      setConfirmOpen(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Accountant package"
        description="Prepare one ZIP of your Schedule E reports, transactions, and receipts for a tax year, to hand to your accountant."
      />
      <PackageDisclaimer />
      <div className="mt-6 space-y-6">
        <PackageContentsList />
        <div className="flex flex-wrap items-center gap-2">
          <label
            htmlFor="package-tax-year"
            className="text-sm font-medium text-fg-muted"
          >
            Tax year
          </label>
          <Select
            id="package-tax-year"
            value={String(taxYear)}
            disabled={active}
            onChange={(event) => setTaxYear(Number(event.target.value))}
          >
            {yearOptions.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </Select>
        </div>
        {allProperties.length > 0 ? (
          <PropertyPicker
            properties={allProperties}
            selectedIds={selectedIds}
            onChange={setPicked}
            disabled={active}
          />
        ) : null}
        <div>
          <Button
            onClick={prepare}
            disabled={active || busy || selectedIds.length === 0}
          >
            Prepare package
          </Button>
        </div>
        {view.showError ? (
          <StateBlock
            kind="error"
            compact
            title="Could not prepare the package"
            description={error ?? undefined}
            onRetry={prepare}
          />
        ) : null}
        <PackageStatusPanel
          job={job}
          deleting={deleting}
          onDelete={() => setConfirmOpen(true)}
        />
      </div>
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Delete package"
        description={
          job
            ? `Delete the package for tax year ${job.tax_year}? The file can no longer be downloaded.`
            : "Delete this package?"
        }
        confirmLabel="Delete"
        pending={deleting}
        onConfirm={confirmDelete}
      />
    </>
  );
}
