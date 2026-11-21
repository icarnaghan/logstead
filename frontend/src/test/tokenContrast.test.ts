import { describe, it, expect } from "vitest";
import css from "../index.css?raw";
import {
  TOKEN_PAIRS,
  contrastRatio,
  parseRgbChannels,
  readTokens,
} from "../lib/contrast";

/**
 * Requirements 17.2, 17.6, 25.1-25.4: every Semantic_Token pair meets its
 * WCAG minimum in both themes, and no indigo values remain.
 */

const tokens = readTokens(css);
const themes = [
  ["light", tokens.light],
  ["dark", tokens.dark],
] as const;

function ratio(theme: Record<string, string>, fg: string, bg: string): number {
  expect(theme[fg], `missing token ${fg}`).toBeDefined();
  expect(theme[bg], `missing token ${bg}`).toBeDefined();
  return contrastRatio(parseRgbChannels(theme[fg]), parseRgbChannels(theme[bg]));
}

describe("token contrast", () => {
  for (const [name, theme] of themes) {
    describe(`${name} theme`, () => {
      it("defines tokens", () => {
        expect(Object.keys(theme).length).toBeGreaterThan(0);
      });

      for (const pair of TOKEN_PAIRS) {
        it(`${pair.fg} on ${pair.bg} >= ${pair.min}:1 (${pair.usage})`, () => {
          expect(ratio(theme, pair.fg, pair.bg)).toBeGreaterThanOrEqual(pair.min);
        });
      }

      it("accent-fg on accent >= 4.5", () => {
        expect(ratio(theme, "accent-fg", "accent")).toBeGreaterThanOrEqual(4.5);
      });
      it("fg-subtle on surface and canvas >= 4.5", () => {
        expect(ratio(theme, "fg-subtle", "surface")).toBeGreaterThanOrEqual(4.5);
        expect(ratio(theme, "fg-subtle", "canvas")).toBeGreaterThanOrEqual(4.5);
      });
      it("border-strong on surface and canvas >= 3", () => {
        expect(ratio(theme, "border-strong", "surface")).toBeGreaterThanOrEqual(3);
        expect(ratio(theme, "border-strong", "canvas")).toBeGreaterThanOrEqual(3);
      });
      it("brand-tagline on canvas >= 4.5", () => {
        expect(ratio(theme, "brand-tagline", "canvas")).toBeGreaterThanOrEqual(4.5);
      });
    });
  }

  it("contains no indigo values", () => {
    // Tailwind indigo 300-700 as space-separated channels.
    const indigo = [
      "165 180 252",
      "129 140 248",
      "99 102 241",
      "79 70 229",
      "67 56 202",
    ];
    for (const [, theme] of themes) {
      for (const value of Object.values(theme)) {
        expect(indigo).not.toContain(value.trim());
      }
    }
    expect(css).not.toMatch(/indigo/i);
    expect(css).not.toMatch(/#(6366f1|4f46e5|4338ca|818cf8|a5b4fc)\b/i);
  });
});
