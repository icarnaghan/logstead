import { useEffect, useRef } from "react";

const APP_NAME = "Logstead";

/** Pure: "{page} - Logstead", or "Logstead" when the page title is empty. */
export function formatDocumentTitle(page: string | null | undefined): string {
  const trimmed = page?.trim();
  return trimmed ? `${trimmed} - ${APP_NAME}` : APP_NAME;
}

/**
 * Sets `document.title` for the current page and restores the previous
 * title on unmount.
 */
export function useDocumentTitle(title: string | null | undefined): void {
  const previousTitle = useRef<string | null>(null);

  // Declared first so the pre-page title is captured before the setter runs.
  useEffect(() => {
    previousTitle.current = document.title;
    return () => {
      if (previousTitle.current !== null) {
        document.title = previousTitle.current;
      }
    };
  }, []);

  useEffect(() => {
    document.title = formatDocumentTitle(title);
  }, [title]);
}
