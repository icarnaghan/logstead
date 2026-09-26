/**
 * The single canonical keyboard-focus indicator, extracted from the exact
 * class fragment repeated across the codebase today. Every focusable shared
 * primitive reuses this constant so the focus ring stays consistent
 * (Requirement 1.2).
 */
export const FOCUS_RING =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
