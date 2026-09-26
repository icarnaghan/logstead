import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { PropertySection } from "../components/PropertySection";
import { AssetList } from "../components/assets/AssetList";
import { AssetForm, type AssetFormValues } from "../components/assets/AssetForm";
import { ScheduleTable } from "../components/assets/ScheduleTable";
import { ApiError } from "../lib/apiClient";
import * as assetsApiDefault from "../api/assets";
import type {
  CreateAssetInput,
  DepreciableAsset,
  ScheduleRow,
  UpdateAssetInput,
} from "../api/assets";

/**
 * Subset of the assets API this page depends on. Injectable so tests can
 * supply a mocked implementation with no network access.
 */
export interface AssetsApi {
  listAssets: (propertyId: string) => Promise<DepreciableAsset[]>;
  createAsset: (
    propertyId: string,
    input: CreateAssetInput,
  ) => Promise<DepreciableAsset>;
  updateAsset: (
    propertyId: string,
    assetId: string,
    input: UpdateAssetInput,
  ) => Promise<DepreciableAsset>;
  deleteAsset: (propertyId: string, assetId: string) => Promise<void>;
  getSchedule: (propertyId: string, assetId: string) => Promise<ScheduleRow[]>;
}

interface AssetsPageProps {
  /** Injectable API layer; defaults to the real module (Requirements 8, 9). */
  api?: AssetsApi;
}

type FieldErrors = Partial<Record<keyof CreateAssetInput, string>>;

/** Pulls a field-specific message out of a 400 ApiError body, if present. */
function toFieldErrors(error: unknown): {
  fieldErrors: FieldErrors;
  message: string;
} {
  if (error instanceof ApiError) {
    const body = error.body;
    if (body && typeof body === "object") {
      const record = body as Record<string, unknown>;
      const field = record.field;
      const message =
        typeof record.message === "string" ? record.message : error.message;
      if (typeof field === "string" && field.length > 0) {
        return {
          fieldErrors: { [field]: message } as FieldErrors,
          message,
        };
      }
      return { fieldErrors: {}, message };
    }
    return { fieldErrors: {}, message: error.message };
  }
  return {
    fieldErrors: {},
    message: "Something went wrong. Please try again.",
  };
}

/**
 * Per-property depreciable assets page (task 23.1, Requirements 8 & 9).
 *
 * Lists a property's depreciable assets, provides an add/edit form (recovery
 * period defaults to 27.5 years when blank, cost basis must be > 0 with the
 * backend's field error surfaced), supports deletion, and lets the user expand
 * each asset's year-by-year straight-line / mid-month depreciation schedule as
 * an accessible numeric table — no charts.
 */
export default function AssetsPage({ api }: AssetsPageProps = {}) {
  const { propertyId = "" } = useParams();
  const assetsApiImpl: AssetsApi = api ?? assetsApiDefault;

  const [assets, setAssets] = useState<DepreciableAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [editing, setEditing] = useState<DepreciableAsset | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [schedule, setSchedule] = useState<ScheduleRow[]>([]);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const [scheduleError, setScheduleError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const list = await assetsApiImpl.listAssets(propertyId);
      setAssets(list);
    } catch {
      setLoadError("Unable to load depreciable assets.");
    } finally {
      setLoading(false);
    }
  }, [assetsApiImpl, propertyId]);

  useEffect(() => {
    if (!propertyId) return;
    void reload();
  }, [propertyId, reload]);

  async function handleSubmit(values: AssetFormValues) {
    setSubmitting(true);
    setFieldErrors({});
    setFormError(null);
    try {
      if (editing) {
        await assetsApiImpl.updateAsset(propertyId, editing.id, values);
      } else {
        await assetsApiImpl.createAsset(propertyId, values);
      }
      setEditing(null);
      // If the edited asset's schedule was open, refresh it to reflect changes.
      if (editing && expandedId === editing.id) {
        void loadSchedule(editing.id);
      }
      await reload();
    } catch (error) {
      const { fieldErrors: fe, message } = toFieldErrors(error);
      setFieldErrors(fe);
      setFormError(message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(asset: DepreciableAsset) {
    try {
      await assetsApiImpl.deleteAsset(propertyId, asset.id);
      if (expandedId === asset.id) {
        setExpandedId(null);
        setSchedule([]);
      }
      if (editing?.id === asset.id) {
        setEditing(null);
      }
      await reload();
    } catch {
      setFormError("Unable to delete the asset. Please try again.");
    }
  }

  const loadSchedule = useCallback(
    async (assetId: string) => {
      setScheduleLoading(true);
      setScheduleError(null);
      try {
        const rows = await assetsApiImpl.getSchedule(propertyId, assetId);
        setSchedule(rows);
      } catch {
        setSchedule([]);
        setScheduleError("Unable to load the depreciation schedule.");
      } finally {
        setScheduleLoading(false);
      }
    },
    [assetsApiImpl, propertyId],
  );

  function handleToggleSchedule(asset: DepreciableAsset) {
    if (expandedId === asset.id) {
      setExpandedId(null);
      setSchedule([]);
      setScheduleError(null);
      return;
    }
    setExpandedId(asset.id);
    void loadSchedule(asset.id);
  }

  const expandedAsset = assets.find((a) => a.id === expandedId) ?? null;

  return (
    <>
      <PropertySection
        propertyId={propertyId}
        title="Depreciable Assets"
        description="Record depreciable assets for this property and review each asset's year-by-year straight-line depreciation schedule."
      />
      <div className="mt-8 space-y-8">
        <section aria-labelledby="asset-form-heading">
          <h2
            id="asset-form-heading"
            className="text-lg font-semibold text-fg"
          >
            {editing ? "Edit asset" : "Add asset"}
          </h2>
          {formError && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {formError}
            </p>
          )}
          <div className="mt-3">
            <AssetForm
              key={editing?.id ?? "new"}
              asset={editing ?? undefined}
              fieldErrors={fieldErrors}
              submitting={submitting}
              onSubmit={handleSubmit}
              onCancel={
                editing
                  ? () => {
                      setEditing(null);
                      setFieldErrors({});
                      setFormError(null);
                    }
                  : undefined
              }
            />
          </div>
        </section>

        <section aria-labelledby="asset-list-heading">
          <h2
            id="asset-list-heading"
            className="text-lg font-semibold text-fg"
          >
            Assets
          </h2>
          {loading ? (
            <p className="mt-3 text-fg-muted">Loading assets…</p>
          ) : loadError ? (
            <p role="alert" className="mt-3 text-sm text-danger">
              {loadError}
            </p>
          ) : (
            <div className="mt-3 space-y-4">
              <AssetList
                assets={assets}
                expandedAssetId={expandedId}
                onEdit={(asset) => {
                  setEditing(asset);
                  setFieldErrors({});
                  setFormError(null);
                }}
                onDelete={handleDelete}
                onToggleSchedule={handleToggleSchedule}
              />

              {expandedAsset && (
                <section
                  aria-labelledby="schedule-heading"
                  className="rounded-lg border border-border bg-surface p-4 shadow-card"
                >
                  <h3
                    id="schedule-heading"
                    className="text-base font-semibold text-fg"
                  >
                    Depreciation schedule: {expandedAsset.description}
                  </h3>
                  {scheduleLoading ? (
                    <p className="mt-2 text-sm text-fg-muted">
                      Loading schedule…
                    </p>
                  ) : scheduleError ? (
                    <p role="alert" className="mt-2 text-sm text-danger">
                      {scheduleError}
                    </p>
                  ) : (
                    <ScheduleTable
                      caption={`Year-by-year depreciation schedule for ${expandedAsset.description}`}
                      rows={schedule}
                    />
                  )}
                </section>
              )}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
