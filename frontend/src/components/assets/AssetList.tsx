import type { DepreciableAsset } from "../../api/assets";
import { formatMoney } from "../../lib/money";
import { Button, ResponsiveTable, type ResponsiveTableColumn } from "../ui";

interface AssetListProps {
  assets: DepreciableAsset[];
  /** Id of the asset whose schedule is currently expanded, if any. */
  expandedAssetId?: string | null;
  onEdit: (asset: DepreciableAsset) => void;
  onDelete: (asset: DepreciableAsset) => void;
  onToggleSchedule: (asset: DepreciableAsset) => void;
}

const COLUMNS: ResponsiveTableColumn[] = [
  { key: "description", header: "Description" },
  { key: "cost_basis", header: "Cost basis", align: "right" },
  { key: "placed_in_service", header: "Placed in service" },
  { key: "recovery_period", header: "Recovery period", align: "right" },
  { key: "actions", header: "Actions" },
];

/**
 * Tabular list of a property's depreciable assets (Requirement 8.7).
 *
 * Each row shows the asset's description, cost basis, placed-in-service date,
 * and recovery period, with actions to edit, delete, or view the year-by-year
 * depreciation schedule (Requirements 8.5, 8.6, 9.4). The schedule itself is
 * rendered by the page below the corresponding row. Layout is delegated to the
 * shared {@link ResponsiveTable} primitive (Requirement 6.3).
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

  const rows = assets.map((asset) => {
    const expanded = expandedAssetId === asset.id;
    return {
      id: asset.id,
      cells: {
        description: <span className="text-fg">{asset.description}</span>,
        cost_basis: (
          <span className="tabular-nums text-fg">
            {formatMoney(asset.cost_basis)}
          </span>
        ),
        placed_in_service: (
          <span className="text-fg">{asset.placed_in_service_date}</span>
        ),
        recovery_period: (
          <span className="tabular-nums text-fg">
            {asset.recovery_period_years}
          </span>
        ),
        actions: (
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => onToggleSchedule(asset)}
              aria-expanded={expanded}
            >
              {expanded ? "Hide schedule" : "View schedule"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => onEdit(asset)}
            >
              Edit
            </Button>
            <Button
              type="button"
              variant="danger"
              size="sm"
              onClick={() => onDelete(asset)}
            >
              Delete
            </Button>
          </div>
        ),
      },
    };
  });

  return (
    <ResponsiveTable
      caption="Depreciable assets for this property"
      columns={COLUMNS}
      rows={rows}
    />
  );
}
