import type { DepreciableAsset } from "../../api/assets";

interface AssetListProps {
  assets: DepreciableAsset[];
  /** Id of the asset whose schedule is currently expanded, if any. */
  expandedAssetId?: string | null;
  onEdit: (asset: DepreciableAsset) => void;
  onDelete: (asset: DepreciableAsset) => void;
  onToggleSchedule: (asset: DepreciableAsset) => void;
}

/**
 * Tabular list of a property's depreciable assets (Requirement 8.7).
 *
 * Each row shows the asset's description, cost basis, placed-in-service date,
 * and recovery period, with actions to edit, delete, or view the year-by-year
 * depreciation schedule (Requirements 8.5, 8.6, 9.4). The schedule itself is
 * rendered by the page below the corresponding row.
 */
export function AssetList({
  assets,
  expandedAssetId,
  onEdit,
  onDelete,
  onToggleSchedule,
}: AssetListProps) {
  if (assets.length === 0) {
    return (
      <p className="text-fg-muted">
        No depreciable assets yet. Add one using the form above.
      </p>
    );
  }

  return (
    <table className="w-full border-collapse text-sm">
      <caption className="sr-only">Depreciable assets for this property</caption>
      <thead>
        <tr className="border-b border-border text-left text-fg-muted">
          <th scope="col" className="py-2 pr-4 font-medium">
            Description
          </th>
          <th scope="col" className="py-2 pr-4 text-right font-medium">
            Cost basis
          </th>
          <th scope="col" className="py-2 pr-4 font-medium">
            Placed in service
          </th>
          <th scope="col" className="py-2 pr-4 text-right font-medium">
            Recovery period
          </th>
          <th scope="col" className="py-2 font-medium">
            Actions
          </th>
        </tr>
      </thead>
      <tbody>
        {assets.map((asset) => {
          const expanded = expandedAssetId === asset.id;
          return (
            <tr key={asset.id} className="border-b border-border align-top">
              <th scope="row" className="py-2 pr-4 font-normal text-fg">
                {asset.description}
              </th>
              <td className="py-2 pr-4 text-right tabular-nums text-fg">
                {asset.cost_basis}
              </td>
              <td className="py-2 pr-4 text-fg">
                {asset.placed_in_service_date}
              </td>
              <td className="py-2 pr-4 text-right tabular-nums text-fg">
                {asset.recovery_period_years}
              </td>
              <td className="py-2">
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => onToggleSchedule(asset)}
                    aria-expanded={expanded}
                    className="rounded-md border border-border px-2 py-1 text-xs font-medium text-fg-muted hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  >
                    {expanded ? "Hide schedule" : "View schedule"}
                  </button>
                  <button
                    type="button"
                    onClick={() => onEdit(asset)}
                    className="rounded-md border border-border px-2 py-1 text-xs font-medium text-fg-muted hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(asset)}
                    className="rounded-md border border-danger px-2 py-1 text-xs font-medium text-danger hover:bg-danger-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  >
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
