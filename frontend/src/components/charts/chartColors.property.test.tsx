import { renderHook } from "@testing-library/react";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import type { ReactNode } from "react";
import { ThemeProvider } from "../../theme/ThemeProvider";
import { useChartColors, type ChartColors } from "./chartColors";

/**
 * Property-based test for the theme-aware chart palette (task 15.2).
 *
 * `useChartColors` must return only semantic-token CSS-variable references, so
 * charts recolor purely by the browser resolving the variable under `.dark`
 * — never a hardcoded palette value (Requirements 11.2, 11.4).
 */

// Feature: ui-polish-and-visualizations, Property 6: Chart colors are always token references

/** Wrap the hook in a ThemeProvider so its `useTheme()` subscription resolves. */
function wrapper({ children }: { children: ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>;
}

/** A token reference of the exact shape `rgb(var(--color-<name>))`. */
const TOKEN_REFERENCE = /^rgb\(var\(--color-[a-z-]+\)\)$/;

/** The keys the palette exposes; the property ranges over this set. */
const COLOR_KEYS: readonly (keyof ChartColors)[] = [
  "accent",
  "success",
  "danger",
  "fg",
  "fgMuted",
  "grid",
];

describe("Property 6: Chart colors are always token references", () => {
  it("every returned color is a token reference and grid resolves to --color-border", () => {
    fc.assert(
      fc.property(
        // Range over the palette keys (in any order, possibly repeated): the
        // invariant must hold for whichever key a chart reads, on any render.
        fc.array(fc.constantFrom(...COLOR_KEYS), { minLength: 1, maxLength: 12 }),
        (keys) => {
          const { result, unmount } = renderHook(() => useChartColors(), {
            wrapper,
          });
          try {
            const colors = result.current;

            for (const key of keys) {
              const value = colors[key];
              expect(
                TOKEN_REFERENCE.test(value),
                `${key} = "${value}" is not a token reference`,
              ).toBe(true);
            }

            // The gridline color derives from --color-border (Req 11.4).
            expect(colors.grid).toBe("rgb(var(--color-border))");
          } finally {
            unmount();
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
