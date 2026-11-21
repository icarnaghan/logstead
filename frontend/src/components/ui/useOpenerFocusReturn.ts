import { useCallback, useRef } from "react";

/**
 * Focus return for dialogs opened outside a list-based `useRecordModal`.
 * Call `rememberOpener()` right before opening; pass `handleCloseAutoFocus` to
 * the dialog's `onCloseAutoFocus`. If the opener is gone (e.g. a closed menu
 * item), focus falls back to `#page-heading`.
 */
export function useOpenerFocusReturn() {
  const openerRef = useRef<Element | null>(null);

  const rememberOpener = useCallback(() => {
    openerRef.current = document.activeElement;
  }, []);

  const handleCloseAutoFocus = useCallback((event: Event) => {
    event.preventDefault();
    const opener = openerRef.current;
    if (opener instanceof HTMLElement && opener.isConnected) {
      opener.focus();
    } else {
      document.getElementById("page-heading")?.focus();
    }
  }, []);

  return { rememberOpener, handleCloseAutoFocus };
}
