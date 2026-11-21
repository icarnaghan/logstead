import { useCallback, useEffect, useRef, useState } from "react";
import { isAsyncLoading, useAsyncResource } from "../../lib/useAsyncResource";

import * as loansApiDefault from "../../api/loans";
import type { Loan, LoanInput } from "../../api/loans";
import { ApiError } from "../../lib/apiClient";
import { LOAN_FIELD_BY_API_NAME, type LoanFormErrors } from "./loanFormModel";

/** The subset of the loans API module the hook uses (test seam). */
export type LoansApi = Pick<
  typeof loansApiDefault,
  "listLoans" | "createLoan" | "updateLoan" | "deleteLoan"
>;

const NO_LOANS: Loan[] = [];
const GENERIC_MESSAGE = "Something went wrong. Please try again.";

/**
 * Maps a failed save to per-field messages and a form-level message
 * (Requirements 9.4, 9.5). A 400 body with `errors` (or a single `field`)
 * puts each message next to its control; anything else (no field, non-400,
 * transport failure) yields only a form-level message.
 */
export function toLoanFormErrors(error: unknown): LoanFormErrors {
  if (!(error instanceof ApiError)) return { form: GENERIC_MESSAGE };
  const body = error.body;
  if (error.status !== 400 || !body || typeof body !== "object") {
    return { form: error.message || GENERIC_MESSAGE };
  }
  const record = body as Record<string, unknown>;
  const message =
    typeof record.message === "string" ? record.message : error.message;

  const result: LoanFormErrors = {};
  const add = (field: unknown, text: unknown) => {
    if (typeof field !== "string" || typeof text !== "string") return;
    const key = LOAN_FIELD_BY_API_NAME[field];
    if (key && result[key] === undefined) result[key] = text;
  };

  if (Array.isArray(record.errors)) {
    for (const entry of record.errors) {
      if (entry && typeof entry === "object") {
        const e = entry as Record<string, unknown>;
        add(e.field, e.message);
      }
    }
  }
  if (Object.keys(result).length === 0) add(record.field, message);

  if (Object.keys(result).length === 0) return { form: message };
  return result;
}

export interface UseLoansResult {
  loans: Loan[];
  loading: boolean;
  /** Message when the list failed to load; null otherwise. */
  loadError: string | null;
  submitting: boolean;
  deleting: boolean;
  /** Per-field and form-level messages from the last failed save. */
  errors: LoanFormErrors;
  /** Message from the last failed delete; null otherwise. */
  deleteError: string | null;
  reload: () => Promise<void>;
  /** Resolves to the saved Loan, or null on failure (errors are set). */
  createLoan: (input: LoanInput) => Promise<Loan | null>;
  updateLoan: (loanId: string, input: LoanInput) => Promise<Loan | null>;
  /** Resolves true on success; on failure the Loan stays in the list. */
  deleteLoan: (loanId: string) => Promise<boolean>;
  clearErrors: () => void;
}

/**
 * Loan list plus create, update and delete state for a property.
 *
 * Failed saves leave the list unchanged and report errors without touching
 * the caller's entered values (Requirements 9.4, 9.5, 9.18).
 */
export function useLoans(
  propertyId: string | undefined,
  api: LoansApi = loansApiDefault,
): UseLoansResult {
  const apiRef = useRef(api);
  useEffect(() => {
    apiRef.current = api;
  });
  // A property switch resets the list; reloads keep it mounted.
  const {
    data: loadedLoans,
    error: loadError,
    status,
    reload,
    setData: setLoans,
  } = useAsyncResource(() => apiRef.current.listLoans(propertyId as string), {
    resetKeys: [propertyId],
    enabled: !!propertyId,
    describeError: () => "Unable to load loans. Please try again.",
  });
  const loans = loadedLoans ?? NO_LOANS;
  const loading = isAsyncLoading(status);
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [errors, setErrors] = useState<LoanFormErrors>({});
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const clearErrors = useCallback(() => {
    setErrors({});
    setDeleteError(null);
  }, []);

  const createLoan = useCallback(
    async (input: LoanInput): Promise<Loan | null> => {
      if (!propertyId) return null;
      setSubmitting(true);
      setErrors({});
      try {
        const created = await apiRef.current.createLoan(propertyId, input);
        setLoans((prev) => [...(prev ?? []), created]);
        return created;
      } catch (error) {
        setErrors(toLoanFormErrors(error));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [propertyId, setLoans],
  );

  const updateLoan = useCallback(
    async (loanId: string, input: LoanInput): Promise<Loan | null> => {
      if (!propertyId) return null;
      setSubmitting(true);
      setErrors({});
      try {
        const updated = await apiRef.current.updateLoan(
          propertyId,
          loanId,
          input,
        );
        setLoans((prev) =>
          (prev ?? []).map((l) => (l.id === loanId ? updated : l)),
        );
        return updated;
      } catch (error) {
        setErrors(toLoanFormErrors(error));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [propertyId, setLoans],
  );

  const deleteLoan = useCallback(
    async (loanId: string): Promise<boolean> => {
      if (!propertyId) return false;
      setDeleting(true);
      setDeleteError(null);
      try {
        await apiRef.current.deleteLoan(propertyId, loanId);
        setLoans((prev) => (prev ?? []).filter((l) => l.id !== loanId));
        return true;
      } catch {
        setDeleteError("Unable to delete the loan. Please try again.");
        return false;
      } finally {
        setDeleting(false);
      }
    },
    [propertyId, setLoans],
  );

  return {
    loans,
    loading,
    loadError,
    submitting,
    deleting,
    errors,
    deleteError,
    reload,
    createLoan,
    updateLoan,
    deleteLoan,
    clearErrors,
  };
}
