import { useEffect, useState } from "react";
import type { DepreciableAsset } from "../../api/assets";

/**
 * Loads the property's depreciable assets to size the tax-year selector
 * (earliest placed-in-service year through now). Degrades to no assets ->
 * the recent-years fallback on any failure.
 */
export function usePropertyAssets(
  propertyId: string,
  loadAssets: (propertyId: string) => Promise<DepreciableAsset[]>,
): DepreciableAsset[] {
  const [assets, setAssets] = useState<DepreciableAsset[]>([]);
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
  return assets;
}
