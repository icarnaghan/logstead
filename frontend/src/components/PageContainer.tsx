import type { ReactNode } from "react";

/**
 * Layout-only page-width convention for the Panel_Pages (Requirements 8.1,
 * 8.2, 9.1, 9.4). This component is purely presentational: it bounds a page's
 * horizontal content width and applies the shared vertical spacing rhythm.
 *
 * Hard boundary (Requirement 10): this wrapper applies width and spacing
 * utilities ONLY (`max-w-*`, `w-*`, `mx-auto`, `space-*`). It introduces no
 * color, typography/type-scale, component visual styling, border-radius,
 * shadow, or design-token classes, and no landmark/heading/focusable element,
 * so existing theming, landmarks, heading structure, and focus order are all
 * preserved unchanged (Requirements 10.2–10.6, 11.1, 11.2).
 *
 * - `wide` (default): the standardized widened max-width tuned for the ~1440px
 *   Desktop_Viewport so panel content fills the available desktop width.
 * - `narrow`: the prior narrower max-width, for any content that should keep
 *   the earlier center-column width.
 */
export function PageContainer({
  width = "wide",
  children,
}: {
  width?: "wide" | "narrow";
  children: ReactNode;
}) {
  const max = width === "wide" ? "max-w-screen-2xl" : "max-w-6xl";
  return <div className={`mx-auto w-full ${max} space-y-section`}>{children}</div>;
}
