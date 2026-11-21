import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { highlightSegments } from "./highlight";

/**
 * Property 14: Highlight segments preserve the text.
 *
 * **Validates: Requirements 11.9**
 */

const normalize = (s: string): string =>
  s.normalize("NFKC").toLowerCase().replace(/\s+/g, " ");

// Mix of plain text, case, unicode (ligatures, full-width, combining marks,
// astral characters) and whitespace so normalization paths are exercised.
const textArb = fc.oneof(
  fc.string({ maxLength: 40 }),
  fc.array(fc.constantFrom("a", "A", "b", "e", "E", " ", "ſ", "ﬁ", "Ａ", "１", "\u0301", "\u00e9", "😀", "\t", "-"), { maxLength: 30 }).map((a) => a.join("")),
  fc.string({ unit: "binary", maxLength: 30 }),
);

const tokenArb = fc.oneof(
  fc.string({ maxLength: 6 }),
  fc.array(fc.constantFrom("a", "A", "b", "e", "f", "i", "Ａ", "１", "\u0301", "\u00e9", "😀", " "), { maxLength: 5 }).map((a) => a.join("")),
);

describe("Property 14: highlightSegments preserves the text", () => {
  it("concatenation equals the input and match segments contain a token", () => {
    fc.assert(
      fc.property(textArb, fc.array(tokenArb, { maxLength: 4 }), (text, tokens) => {
        const segments = highlightSegments(text, tokens);
        expect(segments.map((s) => s.text).join("")).toBe(text);

        const needles = tokens.map((t) => normalize(t).trim()).filter((t) => t.length > 0);
        for (const seg of segments) {
          expect(seg.text.length).toBeGreaterThan(0);
          if (seg.match) {
            const norm = normalize(seg.text);
            expect(needles.some((n) => norm.includes(n))).toBe(true);
          }
        }
      }),
      { numRuns: 300 },
    );
  });

  it("marks a plain case-insensitive match", () => {
    expect(highlightSegments("Hello World", ["wor"])).toEqual([
      { text: "Hello ", match: false },
      { text: "Wor", match: true },
      { text: "ld", match: false },
    ]);
  });

  it("returns no segments for empty text", () => {
    expect(highlightSegments("", ["a"])).toEqual([]);
  });
});
