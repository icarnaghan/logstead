import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getProperty,
  getPropertyNote,
  setPropertyNote,
  ApiError,
  type Property,
} from "../api/properties";
import { listPhotos, type PhotoWithUrl } from "../api/photos";
import { listAssets, type DepreciableAsset } from "../api/assets";
import {
  getReport,
  DEPRECIATION_LINE,
  type ScheduleEReport,
} from "../api/reports";
import { PropertyDetailsView } from "../components/properties/PropertyDetailsView";
import { PropertyPhotos } from "../components/photos";
import { TaxYearSelector } from "../components/dashboard/TaxYearSelector";
import { formatMoney, isLoss } from "../components/dashboard/money";
import { propertyPath } from "../components/navConfig";

type LoadState =
  | { status: "loading" }
  | { status: "loaded"; property: Property }
  | { status: "error"; message: string };

type ReportState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "loaded"; report: ScheduleEReport }
  | { status: "error"; message: string };

interface PropertyDetailPageProps {
  /** Test seam: single-property loader. Defaults to the real `getProperty`. */
  load?: (id: string, signal?: AbortSignal) => Promise<Property>;
  /** Test seam: Schedule E report loader. Defaults to the real `getReport`. */
  loadReport?: (propertyId: string, taxYear: number) => Promise<ScheduleEReport>;
  /** Test seam: per-property photo loader. Defaults to the real `listPhotos`. */
  loadPhotos?: (propertyId: string) => Promise<PhotoWithUrl[]>;
  /** Test seam: per-property asset loader (drives the tax-year range). */
  loadAssets?: (propertyId: string) => Promise<DepreciableAsset[]>;
  /** Test seam: note loader. Defaults to the real `getPropertyNote`. */
  loadNote?: (propertyId: string, signal?: AbortSignal) => Promise<string>;
  /** Test seam: note saver. Defaults to the real `setPropertyNote`. */
  saveNote?: (propertyId: string, text: string) => Promise<string>;
}

/**
 * Build the selectable tax years, newest first: from the earliest depreciable
 * asset's placed-in-service year through the current year. When a property has
 * no assets yet, fall back to a recent-years window so the selector is never
 * empty. A `+1` guard caps a future-dated in-service year at the current year.
 */
function taxYearRange(
  assets: readonly DepreciableAsset[],
  fallbackCount = 6,
): number[] {
  const current = new Date().getFullYear();
  let earliest = current - (fallbackCount - 1);
  for (const asset of assets) {
    const year = Number(asset.placed_in_service_date?.slice(0, 4));
    if (Number.isFinite(year) && year >= 1900 && year < earliest) {
      earliest = year;
    }
  }
  earliest = Math.min(earliest, current); // never start after the current year
  const span = current - earliest + 1;
  return Array.from({ length: span }, (_, index) => current - index);
}

/** Shared tile shell — a rounded surface card with a labelled heading. */
function Tile({
  title,
  headingId,
  children,
  className,
}: {
  title: string;
  headingId: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      aria-labelledby={headingId}
      className={[
        "rounded-lg border border-border bg-surface shadow-card p-4",
        className ?? "",
      ].join(" ")}
    >
      <h2 id={headingId} className="text-sm font-medium text-fg-subtle">
        {title}
      </h2>
      <div className="mt-2">{children}</div>
    </section>
  );
}

/** Income / expenses / net tile driven by the selected year's report. */
function IncomeExpenseTile({ report }: { report: ReportState }) {
  return (
    <Tile title="Income & expenses (year-end)" headingId="tile-income">
      {report.status === "loading" ? (
        <p className="text-sm text-fg-subtle" role="status">
          Loading totals…
        </p>
      ) : report.status === "error" ? (
        <p role="alert" className="text-sm text-danger">
          {report.message}
        </p>
      ) : report.status === "loaded" ? (
        <dl className="space-y-2">
          <div className="flex items-baseline justify-between gap-4">
            <dt className="text-sm text-fg-muted">Total income</dt>
            <dd className="tabular-nums font-semibold text-fg">
              {formatMoney(report.report.totals.total_income)}
            </dd>
          </div>
          <div className="flex items-baseline justify-between gap-4">
            <dt className="text-sm text-fg-muted">Total expenses</dt>
            <dd className="tabular-nums font-semibold text-fg">
              {formatMoney(report.report.totals.total_expenses)}
            </dd>
          </div>
          <div className="flex items-baseline justify-between gap-4 border-t border-border pt-2">
            <dt className="text-sm font-medium text-fg-muted">
              {isLoss(report.report.totals.net) ? "Net loss" : "Net income"}
            </dt>
            <dd
              className={[
                "tabular-nums text-lg font-semibold",
                isLoss(report.report.totals.net)
                  ? "text-danger"
                  : "text-success",
              ].join(" ")}
            >
              {formatMoney(report.report.totals.net)}
              {isLoss(report.report.totals.net) ? (
                <span className="ml-2 align-middle text-xs font-medium uppercase tracking-wide text-danger">
                  Loss
                </span>
              ) : null}
            </dd>
          </div>
        </dl>
      ) : null}
    </Tile>
  );
}

/** Depreciation tile: the Line 18 total from the selected year's report. */
function DepreciationTile({ report }: { report: ReportState }) {
  const total =
    report.status === "loaded"
      ? (report.report.lines.find((l) => l.line === DEPRECIATION_LINE)?.total ??
        "0.00")
      : null;
  return (
    <Tile title="Depreciation" headingId="tile-depreciation">
      {report.status === "loading" ? (
        <p className="text-sm text-fg-subtle" role="status">
          Loading…
        </p>
      ) : report.status === "error" ? (
        <p role="alert" className="text-sm text-danger">
          {report.message}
        </p>
      ) : total !== null ? (
        <>
          <p className="tabular-nums text-2xl font-semibold text-fg">
            {formatMoney(total)}
          </p>
          <p className="mt-1 text-xs text-fg-subtle">
            Schedule E Line 18 for this tax year.
          </p>
        </>
      ) : null}
    </Tile>
  );
}

/** Inline-editable free-text note tile (backed by the notes API). */
function NotesTile({
  propertyId,
  loadNote,
  saveNote,
}: {
  propertyId: string;
  loadNote: (propertyId: string, signal?: AbortSignal) => Promise<string>;
  saveNote: (propertyId: string, text: string) => Promise<string>;
}) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    loadNote(propertyId, controller.signal)
      .then((value) => setText(value))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setError(
          err instanceof ApiError ? err.message : "Could not load the note.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [loadNote, propertyId]);

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSavedMessage(null);
    try {
      const saved = await saveNote(propertyId, text);
      setText(saved);
      setSavedMessage("Saved");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not save the note.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Tile title="Notes" headingId="tile-notes">
      {loading ? (
        <p className="text-sm text-fg-subtle" role="status">
          Loading note…
        </p>
      ) : (
        <div className="space-y-2">
          <label htmlFor="property-note" className="sr-only">
            Property note
          </label>
          <textarea
            id="property-note"
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              setSavedMessage(null);
            }}
            rows={4}
            placeholder="Add a note about this property…"
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          />
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving}
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg hover:bg-accent-hover disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            {savedMessage ? (
              <span role="status" className="text-sm text-success">
                {savedMessage}
              </span>
            ) : null}
          </div>
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
        </div>
      )}
    </Tile>
  );
}

/** A single quicklink button styled like a bordered nav pill. */
function QuickLink({ to, label }: { to: string; label: string }) {
  return (
    <Link
      to={to}
      className="inline-flex rounded-md border border-border px-3 py-1.5 text-sm font-medium text-fg-muted hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      {label}
    </Link>
  );
}

/**
 * Per-property tiled dashboard (Requirement 2.9).
 *
 * Revamps the property overview into a REI-Hub-style grid of tiles for a single
 * property, driven by a tax-year selector at the top. Tiles cover the property
 * header (photo + name + address + type + photo upload), income/expenses/net
 * for the selected year (from the Schedule E report totals), depreciation (the
 * Line 18 total from the same report), a link to the full Schedule E report,
 * stored RentCast property details, a link to supporting documents
 * (transactions), an editable free-text note, and quicklinks into the
 * property's sub-sections. Money is rendered from its two-decimal string form
 * and never re-derived from a float.
 */
export default function PropertyDetailPage({
  load = getProperty,
  loadReport = getReport,
  loadPhotos = listPhotos,
  loadAssets = listAssets,
  loadNote = getPropertyNote,
  saveNote = setPropertyNote,
}: PropertyDetailPageProps) {
  const { propertyId } = useParams<{ propertyId: string }>();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [headerPhoto, setHeaderPhoto] = useState<string | null>(null);

  const currentYear = useMemo(() => new Date().getFullYear(), []);
  const [assets, setAssets] = useState<DepreciableAsset[]>([]);
  // Tax years span from the earliest asset's in-service year to now; recompute
  // when the loaded assets change (falls back to recent years when none).
  const years = useMemo(() => taxYearRange(assets), [assets]);
  const [taxYear, setTaxYear] = useState<number>(currentYear);
  const [report, setReport] = useState<ReportState>({ status: "idle" });

  const refresh = useCallback(
    (signal?: AbortSignal) => {
      if (!propertyId) return;
      setState({ status: "loading" });
      load(propertyId, signal)
        .then((property) => setState({ status: "loaded", property }))
        .catch((err) => {
          if (signal?.aborted) return;
          const message =
            err instanceof ApiError && err.status === 404
              ? "That property could not be found."
              : err instanceof ApiError
                ? err.message
                : "Could not load this property.";
          setState({ status: "error", message });
        });
    },
    [propertyId, load],
  );

  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  // Load the header photo (first photo, if any).
  useEffect(() => {
    if (!propertyId) return;
    let active = true;
    loadPhotos(propertyId)
      .then((photos) => {
        if (active) setHeaderPhoto(photos[0]?.display_url ?? null);
      })
      .catch(() => {
        if (active) setHeaderPhoto(null);
      });
    return () => {
      active = false;
    };
  }, [loadPhotos, propertyId]);

  // Load the property's depreciable assets to size the tax-year selector
  // (earliest placed-in-service year through now). Degrades to no assets ->
  // the recent-years fallback on any failure.
  useEffect(() => {
    if (!propertyId) return;
    let active = true;
    loadAssets(propertyId)
      .then((rows) => {
        if (active) setAssets(rows);
      })
      .catch(() => {
        if (active) setAssets([]);
      });
    return () => {
      active = false;
    };
  }, [loadAssets, propertyId]);

  // (Re)load the Schedule E report whenever the property or tax year changes
  // (drives the income/expense and depreciation tiles).
  useEffect(() => {
    if (!propertyId) return;
    let active = true;
    setReport({ status: "loading" });
    loadReport(propertyId, taxYear)
      .then((r) => {
        if (active) setReport({ status: "loaded", report: r });
      })
      .catch((err) => {
        if (!active) return;
        setReport({
          status: "error",
          message:
            err instanceof ApiError
              ? err.message
              : "Could not load the report.",
        });
      });
    return () => {
      active = false;
    };
  }, [loadReport, propertyId, taxYear]);

  return (
    <section aria-labelledby="property-heading">
      <p className="text-sm">
        <Link
          to="/properties"
          className="text-accent underline underline-offset-2 hover:text-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          ← All properties
        </Link>
      </p>

      {state.status === "loading" ? (
        <p className="mt-4 text-fg-subtle" role="status">
          Loading property…
        </p>
      ) : null}

      {state.status === "error" ? (
        <p
          role="alert"
          className="mt-4 rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger"
        >
          {state.message}
        </p>
      ) : null}

      {state.status === "loaded" ? (
        <>
          {/* Header tile: photo + identity + tax-year selector. */}
          <div className="mt-3 flex flex-col gap-4 rounded-lg border border-border bg-surface shadow-card p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-4">
              <div className="h-20 w-28 shrink-0 overflow-hidden rounded-md bg-surface-muted">
                {headerPhoto ? (
                  <img
                    src={headerPhoto}
                    alt={`Photo of ${state.property.name}`}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <div
                    aria-hidden="true"
                    className="flex h-full w-full items-center justify-center text-fg-subtle"
                  >
                    <svg
                      viewBox="0 0 24 24"
                      className="h-8 w-8"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M3 10.5 12 3l9 7.5" />
                      <path d="M5 9.5V21h14V9.5" />
                      <path d="M9.5 21v-6h5v6" />
                    </svg>
                  </div>
                )}
              </div>
              <div>
                <h1
                  id="property-heading"
                  className="text-2xl font-semibold text-fg"
                >
                  {state.property.name}
                </h1>
                <p className="mt-1 text-fg-muted">
                  {state.property.address_text}
                </p>
                {state.property.property_type ? (
                  <p className="mt-1 text-sm text-fg-subtle">
                    {state.property.property_type}
                  </p>
                ) : null}
              </div>
            </div>
            <TaxYearSelector value={taxYear} years={years} onChange={setTaxYear} />
          </div>

          {/* Tile grid. */}
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <IncomeExpenseTile report={report} />
            <DepreciationTile report={report} />

            <Tile title="Schedule E report" headingId="tile-report">
              <p className="text-sm text-fg-muted">
                View the full Schedule E line-by-line report for the selected
                tax year.
              </p>
              <div className="mt-3">
                <QuickLink
                  to={propertyPath(state.property.id, "reports")}
                  label="Open report"
                />
              </div>
            </Tile>

            <Tile title="Supporting documents" headingId="tile-documents">
              <p className="text-sm text-fg-muted">
                Receipts and documents are attached to transactions.
              </p>
              <div className="mt-3">
                <QuickLink
                  to={propertyPath(state.property.id, "transactions")}
                  label="View transactions"
                />
              </div>
            </Tile>

            <NotesTile
              propertyId={state.property.id}
              loadNote={loadNote}
              saveNote={saveNote}
            />

            <Tile
              title="Quicklinks"
              headingId="tile-quicklinks"
              className="sm:col-span-2 lg:col-span-1"
            >
              <div className="flex flex-wrap gap-2">
                <QuickLink
                  to={propertyPath(state.property.id, "transactions")}
                  label="Transactions"
                />
                <QuickLink
                  to={propertyPath(state.property.id, "assets")}
                  label="Depreciable Assets"
                />
                <QuickLink
                  to={propertyPath(state.property.id, "reports")}
                  label="Schedule E Report"
                />
              </div>
            </Tile>

            <Tile
              title="Property details"
              headingId="tile-details"
              className="sm:col-span-2 lg:col-span-3"
            >
              {state.property.details ? (
                <PropertyDetailsView details={state.property.details} />
              ) : (
                <p className="text-sm text-fg-subtle">
                  No additional property details are on file. Details are added
                  automatically when a property is created from an address that
                  RentCast has data for.
                </p>
              )}
            </Tile>

            <div className="rounded-lg border border-border bg-surface shadow-card p-4 sm:col-span-2 lg:col-span-3">
              <PropertyPhotos propertyId={state.property.id} />
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}
