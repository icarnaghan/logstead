import { useEffect, useRef } from "react";
import { firstInvalidField, type ErrorSummaryItem } from "../../lib/formErrors";
import { FOCUS_RING } from "./focusRing";

export interface ErrorSummaryProps {
  /** Field errors first, then form-level messages without a field. */
  items: ErrorSummaryItem[];
  /** Maps a field key to the id of its control (link target). */
  idFor: (field: string) => string;
  headingId?: string;
}

/**
 * Form error summary (Requirement 11). Renders nothing when empty.
 */
export function ErrorSummary({ items, idFor, headingId }: ErrorSummaryProps) {
  if (items.length === 0) return null;
  const heading =
    items.length === 1
      ? "There is 1 error"
      : `There are ${items.length} errors`;
  return (
    <div
      role="alert"
      aria-labelledby={headingId}
      className="rounded-md border border-danger bg-danger/5 p-3 text-sm text-danger"
    >
      <h2 id={headingId} className="font-semibold">
        {heading}
      </h2>
      <ul className="mt-1 list-disc pl-5">
        {items.map((item, i) => (
          <li key={`${item.field ?? "form"}-${i}`}>
            {item.field !== undefined ? (
              <button
                type="button"
                className={`relative text-left underline before:absolute before:-inset-2 before:content-[''] ${FOCUS_RING}`}
                onClick={() => {
                  document.getElementById(idFor(item.field as string))?.focus();
                }}
              >
                {item.message}
              </button>
            ) : (
              <span>{item.message}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export interface UseFocusFirstInvalidOptions<K extends string> {
  errors: Partial<Record<K, string>>;
  /** Field keys in document order. */
  order: readonly K[];
  idFor: (field: K) => string;
  /** Counter incremented on each failed submit / new server field error. */
  attempt: number;
}

/**
 * Focuses the first invalid field (document order) when `attempt` changes.
 * Form-level-only errors do not move focus.
 */
export function useFocusFirstInvalid<K extends string>({
  errors,
  order,
  idFor,
  attempt,
}: UseFocusFirstInvalidOptions<K>): void {
  const last = useRef(attempt);
  useEffect(() => {
    if (last.current === attempt) return;
    last.current = attempt;
    const field = firstInvalidField(errors, order);
    if (field === undefined) return;
    document.getElementById(idFor(field))?.focus();
    // Only re-run when the attempt counter changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);
}
