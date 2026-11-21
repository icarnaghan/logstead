import type {
  CreateAssetInput,
  DepreciableAsset,
  ScheduleRow,
  UpdateAssetInput,
} from "../../api/assets";

/**
 * Subset of the assets API the Assets page depends on. Injectable so tests can
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
