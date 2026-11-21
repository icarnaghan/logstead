import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

export interface BadgeProps {
  /** Visible short label, e.g. "Imported". */
  children: ReactNode;
  /**
   * Accessible label announced to assistive tech. Defaults to the visible
   * text; pass a fuller phrase when the short label needs more context
   * (e.g. "Imported from a Schedule E import").
   */
  label?: string;
  className?: string;
}

const BADGE_BASE_CLASSES =
  "inline-flex items-center rounded-full border border-accent-subtle bg-accent-subtle px-2 py-0.5 text-xs font-medium text-accent";

/**
 * Small, accessible status pill (Requirements 7.3, 7.4). Used to mark a
 * Schedule E import-synthesized transaction row or report line as "Imported"
 * so backfilled data is visibly distinct from user-tracked data.
 *
 * The pill carries an `aria-label` so screen-reader users hear a clear phrase
 * even though the visible text is terse, and token-only styling keeps it
 * consistent with the rest of the UI.
 */
export function Badge({ children, label, className }: BadgeProps) {
  const accessibleLabel =
    label ?? (typeof children === "string" ? children : undefined);
  return (
    <span
      className={cn(BADGE_BASE_CLASSES, className)}
      aria-label={accessibleLabel}
    >
      {children}
    </span>
  );
}
