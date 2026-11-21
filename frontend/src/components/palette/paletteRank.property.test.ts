import fc from "fast-check";
import { describe, expect, it } from "vitest";
import type { PaletteItem } from "./paletteItems";
import { moveHighlight, normalize, rankLocal, tokenize } from "./paletteRank";

const wordArb = fc.stringMatching(/^[a-cA-C]{1,3}$/);
const labelArb = fc
  .array(wordArb, { minLength: 1, maxLength: 3 })
  .map((words) => words.join(" "));

const itemsArb = fc
  .array(
    fc.record({
      label: labelArb,
      keywords: fc.array(labelArb, { maxLength: 3 }),
    }),
    { maxLength: 12 },
  )
  .map((rows): PaletteItem[] =>
    rows.map((row, i) => ({
      kind: "destination",
      id: `item-${i}`,
      label: row.label,
      keywords: row.keywords,
      to: `/p/${i}`,
      group: "Pages",
    })),
  );

const queryArb = fc
  .array(fc.oneof(wordArb, fc.constant(" "), fc.constant("  ")), { maxLength: 7 })
  .map((parts) => parts.join(" "));

const limitArb = fc.integer({ min: 0, max: 15 });

function tierOf(item: PaletteItem, query: string): number {
  const tokens = tokenize(query);
  const label = normalize(item.label);
  if (tokens.length > 0 && label === tokens.join(" ")) return 0;
  const words = label.split(" ");
  return tokens.some((t) => words.some((w) => w.startsWith(t))) ? 1 : 2;
}

describe("Property 4: Palette ranking and filtering", () => {
  /** **Validates: Requirements 5.1, 5.4** */
  it("returns only items containing every token in label or keywords", () => {
    fc.assert(
      fc.property(itemsArb, queryArb, limitArb, (items, query, limit) => {
        const tokens = tokenize(query);
        for (const item of rankLocal(items, query, limit)) {
          const haystack = [item.label, ...item.keywords].map(normalize).join(" ");
          for (const token of tokens) expect(haystack).toContain(token);
        }
      }),
      { numRuns: 200 },
    );
  });

  /** **Validates: Requirements 5.1** */
  it("keeps every matching item when the limit is large", () => {
    fc.assert(
      fc.property(itemsArb, queryArb, (items, query) => {
        const tokens = tokenize(query);
        const expected = items.filter((item) => {
          const haystack = [item.label, ...item.keywords].map(normalize).join(" ");
          return tokens.every((t) => haystack.includes(t));
        });
        expect(new Set(rankLocal(items, query, 100))).toEqual(new Set(expected));
      }),
      { numRuns: 200 },
    );
  });

  /** **Validates: Requirements 5.3** */
  it("is deterministic for identical inputs", () => {
    fc.assert(
      fc.property(itemsArb, queryArb, limitArb, (items, query, limit) => {
        expect(rankLocal(items, query, limit)).toEqual(rankLocal(items, query, limit));
      }),
      { numRuns: 200 },
    );
  });

  /** **Validates: Requirements 5.2** */
  it("orders by tier, then item order, then label", () => {
    fc.assert(
      fc.property(itemsArb, queryArb, (items, query) => {
        const result = rankLocal(items, query, 100);
        for (let i = 1; i < result.length; i++) {
          const prev = result[i - 1];
          const cur = result[i];
          const pt = tierOf(prev, query);
          const ct = tierOf(cur, query);
          expect(pt).toBeLessThanOrEqual(ct);
          if (pt === ct) expect(items.indexOf(prev)).toBeLessThan(items.indexOf(cur));
        }
      }),
      { numRuns: 200 },
    );
  });

  /** **Validates: Requirements 5.2** */
  it("ranks an exact label match ahead of word-prefix and substring matches", () => {
    const items: PaletteItem[] = ["xab", "ab c", "ab"].map((label, i) => ({
      kind: "destination",
      id: `i${i}`,
      label,
      keywords: [],
      to: "/",
      group: "Pages",
    }));
    expect(rankLocal(items, "AB", 10).map((i) => i.label)).toEqual(["ab", "ab c", "xab"]);
  });

  /** **Validates: Requirements 5.5** */
  it("returns at most limit items", () => {
    fc.assert(
      fc.property(itemsArb, queryArb, limitArb, (items, query, limit) => {
        expect(rankLocal(items, query, limit).length).toBeLessThanOrEqual(limit);
      }),
      { numRuns: 200 },
    );
  });

  /** **Validates: Requirements 5.1** */
  it("keeps all items in original order for an empty query", () => {
    fc.assert(
      fc.property(itemsArb, fc.constantFrom("", " ", "   "), (items, query) => {
        expect(rankLocal(items, query, 100)).toEqual(items);
      }),
      { numRuns: 100 },
    );
  });
});

describe("Property 5: Highlight index wraps", () => {
  const dirArb = fc.constantFrom<"next" | "prev" | 1 | -1>("next", "prev", 1, -1);

  /** **Validates: Requirements 4.4, 4.5** */
  it("stays in range and forward then backward returns the start", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 50 }).chain((length) =>
          fc.record({
            length: fc.constant(length),
            index: fc.integer({ min: 0, max: length - 1 }),
            dir: dirArb,
          }),
        ),
        ({ length, index, dir }) => {
          const moved = moveHighlight(index, length, dir);
          expect(moved).toBeGreaterThanOrEqual(0);
          expect(moved).toBeLessThan(length);
          const forward = dir === "next" || dir === 1;
          const back = moveHighlight(moved, length, forward ? "prev" : "next");
          expect(back).toBe(index);
        },
      ),
      { numRuns: 200 },
    );
  });

  /** **Validates: Requirements 4.4, 4.5** */
  it("returns -1 for an empty list", () => {
    expect(moveHighlight(0, 0, "next")).toBe(-1);
  });
});
