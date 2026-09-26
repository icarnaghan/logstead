/**
 * Theme-aware chart colors (Requirements 11.2–11.4).
 *
 * Charts draw SVG whose `fill`/`stroke` need concrete color values, but the
 * app's palette lives in CSS custom properties (`--color-accent`, etc.) that
 * flip under the `.dark` class. Rather than snapshot literal `rgb(...)` values
 * in JavaScript, this hook returns **CSS-variable reference strings** of the
 * form `rgb(var(--color-...))`.
 *
 * Why this works:
 * - The browser resolves the CSS variable at *paint time*, so when a theme
 *   toggle rewrites `--color-accent` on `<html>`, every SVG element that used
 *   `rgb(var(--color-accent))` recolors automatically — no JS recomputation.
 * - The hook still calls {@link useTheme} to **subscribe** to the theme
 *   context. That subscription forces a re-render of the consuming chart when
 *   the theme flips (Requirement 11.3), refreshing any color a chart library
 *   caches internally (e.g. legend swatches) rather than reading live from the
 *   DOM. Charts key their re-render on this so the recolor is always applied.
 *
 * There is no hardcoded palette here (Requirement 11.2): every value is a
 * semantic-token reference. The gridline color derives from `--color-border`
 * (Requirement 11.4).
 */

import { useTheme } from "../../theme/ThemeProvider";

/**
 * The set of token-referenced color strings a chart needs. Each value is a
 * `rgb(var(--color-...))` string the SVG resolves at paint time.
 */
export interface ChartColors {
  /** Primary series / bars — `--color-accent`. */
  accent: string;
  /** Positive / gain series — `--color-success`. */
  success: string;
  /** Negative / loss series — `--color-danger`. */
  danger: string;
  /** Foreground text (axis labels, ticks) — `--color-fg`. */
  fg: string;
  /** Muted foreground (secondary labels) — `--color-fg-muted`. */
  fgMuted: string;
  /** Gridlines / axes — derives from `--color-border` (Req 11.4). */
  grid: string;
}

/**
 * Returns the chart palette as CSS-variable reference strings.
 *
 * Subscribes to {@link useTheme} so consuming charts re-render when the theme
 * flips (Requirement 11.3); the returned strings are static references that the
 * SVG resolves against the current theme's variables at paint time.
 */
export function useChartColors(): ChartColors {
  // Subscribe to the theme context: re-render the chart on every toggle so any
  // internally cached color is refreshed (Req 11.3). The returned strings do
  // not depend on the resolved value — the browser resolves the variable.
  useTheme();

  return {
    accent: "rgb(var(--color-accent))",
    success: "rgb(var(--color-success))",
    danger: "rgb(var(--color-danger))",
    fg: "rgb(var(--color-fg))",
    fgMuted: "rgb(var(--color-fg-muted))",
    grid: "rgb(var(--color-border))",
  };
}
