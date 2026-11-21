import { useRef } from "react";
import { useParams } from "react-router-dom";
import { PageContainer } from "../components/PageContainer";
import { PropertySection } from "../components/PropertySection";
import { AssetList } from "../components/assets/AssetList";
import { AssetFormDialog } from "../components/assets/AssetFormDialog";
import { AssetScheduleSection } from "../components/assets/AssetScheduleSection";
import { useAssetEditor } from "../components/assets/useAssetEditor";
import { useAssetSchedule } from "../components/assets/useAssetSchedule";
import type { AssetsApi } from "../components/assets/assetsApi";
import {
  Button,
  EmptyGuide,
  LoadingRegion,
  RefreshingIndicator,
  StateBlock,
  TableSkeleton,
  useFirstLoad,
  useRecordModal,
  useUndoableDelete,
} from "../components/ui";
import { assetToInput } from "../lib/undoMappers";
import { isAsyncLoading, useAsyncResource } from "../lib/useAsyncResource";
import { useNewParam } from "../lib/useNewParam";
import { useFocusParam } from "../lib/useFocusParam";
import { EMPTY_COPY } from "../lib/emptyCopy";
import * as assetsApiDefault from "../api/assets";
import type { DepreciableAsset } from "../api/assets";

export type { AssetsApi };

interface AssetsPageProps {
  /** Injectable API layer; defaults to the real module (Requirements 8, 9). */
  api?: AssetsApi;
}

/** Stable empty list so memoised derivations do not churn before first load. */
const NO_ASSETS: DepreciableAsset[] = [];

/**
 * Per-property depreciable assets page (task 23.1, Requirements 8 & 9).
 *
 * Lists a property's depreciable assets, provides an add/edit form (recovery
 * period defaults to 27.5 years when blank, cost basis must be > 0 with the
 * backend's field error surfaced), supports deletion with Undo, and lets the user expand
 * each asset's year-by-year straight-line / mid-month depreciation schedule as
 * an accessible numeric table — no charts.
 */
export default function AssetsPage({ api }: AssetsPageProps = {}) {
  const { propertyId = "" } = useParams();
  const assetsApiImpl: AssetsApi = api ?? assetsApiDefault;


  // A property switch resets the resource (skeleton, no stale rows); later
  // reloads for the same property keep the list mounted.
  const {
    data: loadedAssets,
    error: loadError,
    status,
    reload,
  } = useAsyncResource(() => assetsApiImpl.listAssets(propertyId), {
    resetKeys: [propertyId],
    enabled: propertyId !== "",
    describeError: () => "Unable to load depreciable assets.",
  });
  const assets = loadedAssets ?? NO_ASSETS;


  const listHeadingRef = useRef<HTMLHeadingElement>(null);
  const modal = useRecordModal(assets, { fallbackFocusRef: listHeadingRef });


  const view = useFirstLoad({
    loading: isAsyncLoading(status),
    error: loadError,
    resetKey: propertyId,
  });

  const sched = useAssetSchedule({
    api: assetsApiImpl,
    propertyId,
    assets,
    reload,
  });

  const editor = useAssetEditor({
    api: assetsApiImpl,
    propertyId,
    modal,
    expandedId: sched.expandedId,
    loadSchedule: sched.loadSchedule,
    reload,
  });

  useNewParam(editor.openAdd, view.showContent);
  useFocusParam(assets, view.showContent);
  // Asset deletes are always Safe_Deletes (Requirement 13.1): Undo re-creates
  // the asset through createAsset with the retained data.
  const undoableDelete = useUndoableDelete<DepreciableAsset>({
    remove: async (asset) => {
      await assetsApiImpl.deleteAsset(propertyId, asset.id);
      if (sched.expandedId === asset.id) sched.clearExpanded();
      modal.onRecordDeleted(asset.id);
    },
    restore: (asset) =>
      assetsApiImpl.createAsset(propertyId, assetToInput(asset)),
    refresh: reload,
    deletedTitle: () => "Asset deleted",
    restoredTitle: "Asset restored",
    restoreFailedTitle: "Could not restore the asset",
    deleteFailedTitle: "Could not delete the asset",
  });

  return (
    <PageContainer>
      <PropertySection
        propertyId={propertyId}
        title="Depreciable Assets"
        description="Record depreciable assets for this property and review each asset's year-by-year straight-line depreciation schedule."
      />

      <div className="mt-8 space-y-8">
        <section aria-labelledby="asset-list-heading">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2
              id="asset-list-heading"
              ref={listHeadingRef}
              tabIndex={-1}
              className="text-lg font-semibold text-fg focus:outline-none"
            >
              Assets
            </h2>
            {view.showContent && assets.length > 0 && (
              <Button variant="primary" size="sm" onClick={editor.openAdd}>
                Add asset
              </Button>
            )}
          </div>
          {view.showSkeleton ? (
            <div className="mt-3">
              <LoadingRegion label="Loading assets">
                <TableSkeleton columns={5} />
              </LoadingRegion>
            </div>
          ) : null}
          {view.showError ? (
            <div className={view.errorIsStale ? "mt-3 mb-4" : "mt-3"}>
              <StateBlock
                kind="error"
                compact={view.errorIsStale}
                title="Could not load depreciable assets"
                description={loadError ?? undefined}
                onRetry={() => void reload()}
              />
            </div>
          ) : null}
          {view.refreshing ? (
            <RefreshingIndicator className="mt-3 mb-4" />
          ) : null}
          {!view.showContent ? null : assets.length === 0 ? (
            <div className="mt-3">
              <EmptyGuide
                title={EMPTY_COPY.assets.title}
                description={EMPTY_COPY.assets.description}
                primary={{
                  label: EMPTY_COPY.assets.primaryLabel,
                  onClick: editor.openAdd,
                }}
              />
            </div>
          ) : (
            <div className="mt-3 space-y-4">
              <AssetList
                assets={assets}
                expandedAssetId={sched.expandedId}
                onEdit={editor.openEdit}
                onDelete={(asset) => void undoableDelete(asset)}
                onToggleSchedule={sched.toggle}
              />

              {sched.expandedAsset && (
                <AssetScheduleSection
                  asset={sched.expandedAsset}
                  schedule={sched.schedule}
                  loading={sched.scheduleLoading}
                  error={sched.scheduleError}
                  overrideErrors={sched.overrideErrors}
                  overrideGeneralError={sched.overrideGeneralError}
                  onRetry={sched.loadSchedule}
                  onOverrideChange={sched.handleOverrideChange}
                />
              )}
            </div>
          )}
        </section>
      </div>

      <AssetFormDialog
        modal={modal}
        editing={editor.editing}
        submitting={editor.submitting}
        formError={editor.formError}
        fieldErrors={editor.fieldErrors}
        onSubmit={editor.handleSubmit}
      />
    </PageContainer>
  );
}
