import { useCallback, useState } from "react";

/** Pure: returns `errors` without the dismissed keys. Does not mutate `errors`. */
export function omitDismissed<K extends string>(
  errors: Partial<Record<K, string>> | undefined,
  dismissed: ReadonlySet<K>,
): Partial<Record<K, string>> {
  const result: Partial<Record<K, string>> = {};
  if (!errors) return result;
  for (const key of Object.keys(errors) as K[]) {
    if (!dismissed.has(key)) result[key] = errors[key];
  }
  return result;
}

/**
 * Tracks which server-error fields the user has edited since the errors
 * object last changed. A new `serverErrors` identity clears the dismissed set.
 */
export function useDismissibleErrors<K extends string>(
  serverErrors: Partial<Record<K, string>> | undefined,
): { errors: Partial<Record<K, string>>; dismiss: (field: K) => void } {
  const [dismissed, setDismissed] = useState<ReadonlySet<K>>(() => new Set());
  const [prevServerErrors, setPrevServerErrors] = useState(serverErrors);

  // Store-previous-prop pattern: reset during render, no effect.
  let current = dismissed;
  if (prevServerErrors !== serverErrors) {
    setPrevServerErrors(serverErrors);
    current = new Set();
    setDismissed(current);
  }

  const dismiss = useCallback((field: K) => {
    setDismissed((prev) => {
      if (prev.has(field)) return prev;
      const next = new Set(prev);
      next.add(field);
      return next;
    });
  }, []);

  return { errors: omitDismissed(serverErrors, current), dismiss };
}
