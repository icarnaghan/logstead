import { useCallback, useState } from "react";
import { useToast } from "../ui";
import type {
  DepreciableAsset,
  ScheduleRow,
  UpdateAssetInput,
} from "../../api/assets";
import type { AssetsApi } from "./assetsApi";
import { toOverrideErrors } from "./assetErrors";

/**
 * Expanded-asset depreciation schedule state plus per-year override saves
 * (Requirements 6.2-6.4).
 */
export function useAssetSchedule({
  api,
  propertyId,
  assets,
  reload,
}: {
  api: AssetsApi;
  propertyId: string;
  assets: DepreciableAsset[];
  reload: () => Promise<unknown>;
}) {
  const { notify } = useToast();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [schedule, setSchedule] = useState<ScheduleRow[]>([]);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const [scheduleError, setScheduleError] = useState<string | null>(null);

  // Per-year override validation messages (keyed by tax-year string) and a
  // general message for a whole-map rejection, surfaced in the schedule UI
  // (Requirement 6.4). Cleared on a successful override save.
  const [overrideErrors, setOverrideErrors] = useState<Record<string, string>>(
    {},
  );
  const [overrideGeneralError, setOverrideGeneralError] = useState<
    string | null
  >(null);

  const loadSchedule = useCallback(
    async (assetId: string) => {
      setScheduleLoading(true);
      setScheduleError(null);
      try {
        const rows = await api.getSchedule(propertyId, assetId);
        setSchedule(rows);
      } catch {
        setSchedule([]);
        setScheduleError("Unable to load the depreciation schedule.");
      } finally {
        setScheduleLoading(false);
      }
    },
    [api, propertyId],
  );

  /** Collapses the open schedule (used when its asset is deleted). */
  function clearExpanded() {
    setExpandedId(null);
    setSchedule([]);
  }

  function toggle(asset: DepreciableAsset) {
    if (expandedId === asset.id) {
      setExpandedId(null);
      setSchedule([]);
      setScheduleError(null);
      setOverrideErrors({});
      setOverrideGeneralError(null);
      return;
    }
    setExpandedId(asset.id);
    setOverrideErrors({});
    setOverrideGeneralError(null);
    void loadSchedule(asset.id);
  }

  const expandedAsset = assets.find((a) => a.id === expandedId) ?? null;

  /**
   * Persists a per-year override for the currently expanded asset
   * (Requirements 6.2, 6.3, 6.4). Builds the updated override map from the
   * asset's existing map — setting `map[String(taxYear)] = amount` for a new
   * value, or deleting that key when `amount` is `null` (clear) — and sends it
   * via `updateAsset` alongside the asset's other editable fields. On success
   * it reloads the asset list (so `expandedAsset.depreciation_overrides` picks
   * up the change) and the schedule (so the re-materialized amounts show),
   * without a full page reload. On a 400 it maps the dotted field into the
   * per-year / general override errors and leaves the schedule unchanged, so a
   * rejected override is never shown as saved.
   */
  async function handleOverrideChange(taxYear: number, amount: string | null) {
    if (!expandedAsset) return;
    const asset = expandedAsset;

    const updatedMap: Record<string, string> = {
      ...(asset.depreciation_overrides ?? {}),
    };
    if (amount === null) {
      delete updatedMap[String(taxYear)];
    } else {
      updatedMap[String(taxYear)] = amount;
    }

    const body: UpdateAssetInput = {
      description: asset.description,
      cost_basis: asset.cost_basis,
      placed_in_service_date: asset.placed_in_service_date,
      recovery_period_years: asset.recovery_period_years,
      depreciation_overrides: updatedMap,
    };

    try {
      await api.updateAsset(propertyId, asset.id, body);
      // Clear any prior override errors only on a successful save.
      setOverrideErrors({});
      setOverrideGeneralError(null);
      // Reload the list so the asset's override map reflects the save, and the
      // schedule so the re-materialized amounts show — no full page reload.
      await reload();
      await loadSchedule(asset.id);
      notify({ variant: "success", title: "Depreciation override saved" });
    } catch (error) {
      const mapped = toOverrideErrors(error);
      if (mapped) {
        setOverrideErrors(mapped.yearErrors);
        setOverrideGeneralError(mapped.generalError);
      } else {
        // A non-field failure falls back to a toast; keep prior inline errors.
        notify({ variant: "error", title: "Could not save the override" });
      }
    }
  }

  return {
    expandedId,
    expandedAsset,
    schedule,
    scheduleLoading,
    scheduleError,
    overrideErrors,
    overrideGeneralError,
    loadSchedule,
    clearExpanded,
    toggle,
    handleOverrideChange,
  };
}
