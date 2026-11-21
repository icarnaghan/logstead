import { ApiError } from "../../lib/apiClient";
import type { CreateAssetInput } from "../../api/assets";

export type FieldErrors = Partial<Record<keyof CreateAssetInput, string>>;

/** Pulls a field-specific message out of a 400 ApiError body, if present. */
export function toFieldErrors(error: unknown): {
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
 * The field name the backend uses for override validation failures
 * (Requirement 6.4). A per-year rejection carries a dotted field
 * `depreciation_overrides.<year>`; a whole-map rejection carries the bare
 * `depreciation_overrides`.
 */
export const OVERRIDE_FIELD = "depreciation_overrides";

/**
 * Splits a 400 ApiError from an override save into the per-year and general
 * schedule messages the schedule UI surfaces (Requirement 6.4). Extends the
 * {@link toFieldErrors} pattern: a dotted `depreciation_overrides.<year>` field
 * maps to `yearErrors[year]`; the bare `depreciation_overrides` field surfaces
 * as a single general message near the schedule. Returns `null` when the error
 * is not a recognizable override field error (the caller then falls back to a
 * generic toast).
 */
export function toOverrideErrors(error: unknown): {
  yearErrors: Record<string, string>;
  generalError: string | null;
  message: string;
} | null {
  if (!(error instanceof ApiError)) return null;
  const body = error.body;
  if (!body || typeof body !== "object") return null;
  const record = body as Record<string, unknown>;
  const field = record.field;
  const message =
    typeof record.message === "string" ? record.message : error.message;
  if (typeof field !== "string" || field.length === 0) return null;

  if (field === OVERRIDE_FIELD) {
    // Whole-map rejection (e.g. sum exceeds basis, tail would go negative):
    // surface it once as a general message near the schedule.
    return { yearErrors: {}, generalError: message, message };
  }
  if (field.startsWith(`${OVERRIDE_FIELD}.`)) {
    const year = field.slice(OVERRIDE_FIELD.length + 1);
    if (year.length > 0) {
      return { yearErrors: { [year]: message }, generalError: null, message };
    }
  }
  return null;
}
