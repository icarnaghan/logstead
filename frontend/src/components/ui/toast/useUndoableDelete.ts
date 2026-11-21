import { useCallback, useRef } from "react";
import { useToast } from "./useToast";

export interface UndoableDeleteOptions<T> {
  remove: (item: T) => Promise<void>;
  /** Re-creates the record through the existing create API. */
  restore: (item: T) => Promise<unknown>;
  refresh: () => Promise<void> | void;
  deletedTitle: (item: T) => string;
  restoredTitle: string;
  restoreFailedTitle: string;
  deleteFailedTitle: string;
}

/**
 * Safe_Delete with an Undo toast (Requirements 13.2-13.6).
 *
 * Returns `run(item)`, resolving `true` when the delete succeeded. On success
 * it refreshes and shows a toast with an Undo action (action toasts last at
 * least 8s; Radix pauses on hover/focus). Undo re-creates the record from the
 * retained item and refreshes. A failed restore shows an error toast and still
 * refreshes so the list matches the server. A failed remove shows an error
 * toast and no Undo.
 *
 * The item and the options (including any captured propertyId) are snapshotted
 * at delete time, so Undo keeps working after the page navigates away.
 */
export function useUndoableDelete<T>(
  opts: UndoableDeleteOptions<T>,
): (item: T) => Promise<boolean> {
  const { notify } = useToast();
  const optsRef = useRef(opts);
  optsRef.current = opts;

  return useCallback(
    async (item: T) => {
      const o = optsRef.current;

      const safeRefresh = async () => {
        try {
          await o.refresh();
        } catch {
          // A failed refresh must not break the delete/undo flow.
        }
      };

      try {
        await o.remove(item);
      } catch {
        notify({ variant: "error", title: o.deleteFailedTitle });
        return false;
      }

      await safeRefresh();

      notify({
        variant: "success",
        title: o.deletedTitle(item),
        action: {
          label: "Undo",
          onClick: () => {
            void (async () => {
              try {
                await o.restore(item);
                await safeRefresh();
                notify({ variant: "success", title: o.restoredTitle });
              } catch {
                notify({ variant: "error", title: o.restoreFailedTitle });
                await safeRefresh();
              }
            })();
          },
        },
      });
      return true;
    },
    [notify],
  );
}
