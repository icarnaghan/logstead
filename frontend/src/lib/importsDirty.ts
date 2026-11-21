import { createContext, useEffect } from "react";

export interface ImportsDirtyValue {
  dirty: boolean;
  setDirty: (dirty: boolean) => void;
}

/** Dirty state shared by the Imports layout, its tabs and the active form. */
export const ImportsDirtyContext = createContext<ImportsDirtyValue>({
  dirty: false,
  setDirty: () => {},
});

function handleBeforeUnload(event: BeforeUnloadEvent) {
  event.preventDefault();
  event.returnValue = "";
}

/** Adds a `beforeunload` guard while `dirty`; removed when clean or unmounted. */
export function useBeforeUnloadWhen(dirty: boolean): void {
  useEffect(() => {
    if (!dirty) return;
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [dirty]);
}
