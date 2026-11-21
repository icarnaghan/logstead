/**
 * Helpers for the form Error_Summary (Requirement 11).
 */

export interface ErrorSummaryItem {
  /** Field key the error belongs to; absent for form-level messages. */
  field?: string;
  message: string;
}

/** Entries with a non-empty message, in the given (document) order. */
export function orderedErrors<K extends string>(
  errors: Partial<Record<K, string>>,
  order: readonly K[],
): { field: K; message: string }[] {
  const result: { field: K; message: string }[] = [];
  for (const field of order) {
    const message = errors[field];
    if (typeof message === "string" && message.length > 0) {
      result.push({ field, message });
    }
  }
  return result;
}

/** First field in `order` that has a non-empty error, or undefined. */
export function firstInvalidField<K extends string>(
  errors: Partial<Record<K, string>>,
  order: readonly K[],
): K | undefined {
  return orderedErrors(errors, order)[0]?.field;
}
