import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

/** True iff the route change should move focus and announce (pathname change, not first run). */
export function shouldHandleRouteChange(
  prevPath: string,
  nextPath: string,
  isInitial: boolean,
): boolean {
  return !isInitial && prevPath !== nextPath;
}

const TITLE_SUFFIX = " - Logstead";

function currentPageTitle(): string {
  let title = (document.title ?? "").trim();
  if (title.endsWith(TITLE_SUFFIX)) {
    title = title.slice(0, -TITLE_SUFFIX.length).trim();
  }
  return title || "Logstead";
}

/**
 * Moves focus to the page heading (or main region) after a route change and
 * announces the page title through a polite live region.
 */
export function RouteAnnouncer() {
  const { pathname } = useLocation();
  const prevPath = useRef(pathname);
  const isInitial = useRef(true);
  const [message, setMessage] = useState("");

  useEffect(() => {
    const initial = isInitial.current;
    const prev = prevPath.current;
    isInitial.current = false;
    prevPath.current = pathname;

    if (!shouldHandleRouteChange(prev, pathname, initial)) return;

    const target =
      document.querySelector<HTMLElement>("main h1") ??
      document.getElementById("main-content");
    if (target) {
      if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
      target.focus();
    }

    setMessage("");
    const frame = requestAnimationFrame(() => setMessage(currentPageTitle()));
    return () => cancelAnimationFrame(frame);
  }, [pathname]);

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className="sr-only"
    >
      {message}
    </div>
  );
}

export default RouteAnnouncer;
