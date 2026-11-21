import { useCallback } from "react";
import type { CarryforwardApi } from "../../api/carryforward";

/**
 * Save/clear handlers for the reconciliation page. Each calls the API and then
 * reloads the whole series in place (no full page reload) so
 * expected/reported/status update together (Requirements 5.6, 6.4). Errors
 * propagate to the calling control so it can surface them inline (the controls
 * await these promises).
 */
export function useCarryforwardActions(
  api: CarryforwardApi,
  load: () => Promise<unknown> | void,
) {
  const handleSaveReported = useCallback(
    async (taxYear: number, amount: string) => {
      await api.setReported(taxYear, amount);
      await load();
    },
    [api, load],
  );

  const handleClearReported = useCallback(
    async (taxYear: number) => {
      await api.clearReported(taxYear);
      await load();
    },
    [api, load],
  );

  const handleSaveOpeningBalance = useCallback(
    async (amount: string) => {
      await api.setOpeningBalance(amount);
      await load();
    },
    [api, load],
  );

  const handleSetAllowed = useCallback(
    async (taxYear: number, amount: string) => {
      await api.setAllowedLoss(taxYear, amount);
      await load();
    },
    [api, load],
  );

  const handleClearAllowed = useCallback(
    async (taxYear: number) => {
      await api.clearAllowedLoss(taxYear);
      await load();
    },
    [api, load],
  );

  const handleSetFullyAllowed = useCallback(
    async (taxYear: number, on: boolean) => {
      await api.setFullyAllowed(taxYear, on);
      await load();
    },
    [api, load],
  );

  return {
    handleSaveReported,
    handleClearReported,
    handleSaveOpeningBalance,
    handleSetAllowed,
    handleClearAllowed,
    handleSetFullyAllowed,
  };
}
