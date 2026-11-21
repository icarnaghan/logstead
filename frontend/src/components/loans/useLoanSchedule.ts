import { useCallback, useEffect, useRef, useState } from "react";

import * as loansApiDefault from "../../api/loans";
import type { LoanSchedule } from "../../api/loans";
import { ApiError } from "../../lib/apiClient";
import { isAsyncLoading, useAsyncResource } from "../../lib/useAsyncResource";

/** The subset of the loans API module the hook uses (test seam). */
export type LoanScheduleApi = Pick<
  typeof loansApiDefault,
  "getLoanSchedule" | "setInterestOverride" | "clearInterestOverride"
>;

const OVERRIDE_FIELD = "interest_overrides";
const GENERIC_MESSAGE = "Something went wrong. Please try again.";

/**
 * Splits a failed override save into a per-year message (dotted
 * `interest_overrides.<year>` field) or a general message otherwise
 * (Requirements 9.12, 9.13).
 */
function toOverrideError(
  error: unknown,
  taxYear: number,
): { year: string; message: string } {
  const year = String(taxYear);
  if (error instanceof ApiError) {
    const body = error.body;
    let message = error.message || GENERIC_MESSAGE;
    if (body && typeof body === "object") {
      const record = body as Record<string, unknown>;
      if (typeof record.message === "string") message = record.message;
      const field = record.field;
      if (
        typeof field === "string" &&
        field.startsWith(`${OVERRIDE_FIELD}.`) &&
        field.length > OVERRIDE_FIELD.length + 1
      ) {
        return { year: field.slice(OVERRIDE_FIELD.length + 1), message };
      }
    }
    return { year, message };
  }
  return { year, message: GENERIC_MESSAGE };
}

export interface UseLoanScheduleResult {
  schedule: LoanSchedule | null;
  loading: boolean;
  /** Message when the schedule failed to load; null otherwise. */
  loadError: string | null;
  /** Per-year override error messages keyed by tax year string. */
  yearErrors: Record<string, string>;
  /** Tax year currently being saved or cleared, or null. */
  savingYear: number | null;
  refresh: () => Promise<void>;
  /** Resolves true on success; on failure the year's error is set. */
  setOverride: (taxYear: number, interest: string) => Promise<boolean>;
  clearOverride: (taxYear: number) => Promise<boolean>;
}

/**
 * Loads a Loan's schedule and supports override set/clear with per-year
 * errors. Passing a null `loanId` clears the state. After a successful
 * override change the schedule is refreshed so rollups and variance are
 * authoritative from the backend.
 */
export function useLoanSchedule(
  propertyId: string | undefined,
  loanId: string | null | undefined,
  api: LoanScheduleApi = loansApiDefault,
): UseLoanScheduleResult {
  const [yearErrors, setYearErrors] = useState<Record<string, string>>({});
  const [savingYear, setSavingYear] = useState<number | null>(null);
  const apiRef = useRef(api);
  useEffect(() => {
    apiRef.current = api;
  });
  // Switching loan or property resets the schedule; reloads keep it mounted.
  const {
    data: schedule,
    error: loadError,
    status,
    reload: refresh,
  } = useAsyncResource(
    () =>
      apiRef.current.getLoanSchedule(propertyId as string, loanId as string),
    {
      resetKeys: [propertyId, loanId],
      enabled: !!propertyId && !!loanId,
      describeError: () => "Unable to load the schedule. Please try again.",
    },
  );
  const loading = isAsyncLoading(status);
  useEffect(() => {
    setYearErrors({});
  }, [propertyId, loanId]);
  const runOverride = useCallback(
    async (taxYear: number, action: () => Promise<unknown>) => {
      if (!propertyId || !loanId) return false;
      setSavingYear(taxYear);
      setYearErrors((prev) => {
        const next = { ...prev };
        delete next[String(taxYear)];
        return next;
      });
      try {
        await action();
      } catch (error) {
        const { year, message } = toOverrideError(error, taxYear);
        setYearErrors((prev) => ({ ...prev, [year]: message }));
        setSavingYear(null);
        return false;
      }
      setSavingYear(null);
      await refresh();
      return true;
    },
    [propertyId, loanId, refresh],
  );

  const setOverride = useCallback(
    (taxYear: number, interest: string) =>
      runOverride(taxYear, () =>
        apiRef.current.setInterestOverride(
          propertyId as string,
          loanId as string,
          taxYear,
          interest,
        ),
      ),
    [propertyId, loanId, runOverride],
  );

  const clearOverride = useCallback(
    (taxYear: number) =>
      runOverride(taxYear, () =>
        apiRef.current.clearInterestOverride(
          propertyId as string,
          loanId as string,
          taxYear,
        ),
      ),
    [propertyId, loanId, runOverride],
  );

  return {
    schedule,
    loading,
    loadError,
    yearErrors,
    savingYear,
    refresh,
    setOverride,
    clearOverride,
  };
}
