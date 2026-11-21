import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { nextSortState, sortRows, type SortState, type SortType } from "./tableSort";

/**
 * Property-based tests for the pure ResponsiveTable sort helpers (task 31).
 */

const keyArb = fc.string({ minLength: 1, maxLength: 12 });
const directionArb = fc.constantFrom<"asc" | "desc">("asc", "desc");
const stateArb: fc.Arbitrary<SortState> = fc.oneof(
  fc.constant(null),
  fc.record({ key: keyArb, direction: directionArb }),
);

describe("tableSort properties", () => {
  // Feature: ui-polish-and-consistency, Property 17: Sort state cycles through three states
  it("Property 17: Sort state cycles through three states", () => {
    // **Validates: Requirements 20.1**
    fc.assert(
      fc.property(keyArb, keyArb, stateArb, (k, other, current) => {
        expect(nextSortState(null, k)).toEqual({ key: k, direction: "asc" });
        expect(nextSortState({ key: k, direction: "asc" }, k)).toEqual({ key: k, direction: "desc" });
        expect(nextSortState({ key: k, direction: "desc" }, k)).toBeNull();

        // A different key than the current one always starts at asc.
        if (current && current.key !== k) {
          expect(nextSortState(current, k)).toEqual({ key: k, direction: "asc" });
        }
        if (other !== k) {
          expect(nextSortState({ key: other, direction: "desc" }, k)).toEqual({ key: k, direction: "asc" });
        }

        // Three applications on the same key from null return to null.
        const once = nextSortState(null, k);
        const twice = nextSortState(once, k);
        expect(nextSortState(twice, k)).toBeNull();
      }),
      { numRuns: 100 },
    );
  });

  // Feature: ui-polish-and-consistency, Property 18: Sorting orders rows and preserves them
  it("Property 18: Sorting orders rows and preserves them", () => {
    // **Validates: Requirements 20.3, 20.4, 20.6**
    type Row = { id: number; v: string | number | null | undefined };

    const present: Record<SortType, fc.Arbitrary<string | number>> = {
      text: fc.stringMatching(/^[a-z]{1,6}$/),
      number: fc.integer({ min: -1000, max: 1000 }),
      date: fc
        .date({ min: new Date("2000-01-01T00:00:00Z"), max: new Date("2040-12-31T00:00:00Z"), noInvalidDate: true })
        .map((d) => d.toISOString().slice(0, 10)),
    };
    const cmp: Record<SortType, (a: string | number, b: string | number) => number> = {
      text: (a, b) => (a < b ? -1 : a > b ? 1 : 0),
      number: (a, b) => (a as number) - (b as number),
      date: (a, b) => (a < b ? -1 : a > b ? 1 : 0),
    };

    const scenarioArb = fc
      .constantFrom<SortType>("text", "number", "date")
      .chain((type) =>
        fc.record({
          type: fc.constant(type),
          direction: directionArb,
          values: fc.array(fc.oneof(present[type], fc.constant(null), fc.constant(undefined)), { maxLength: 30 }),
        }),
      );

    fc.assert(
      fc.property(scenarioArb, ({ type, direction, values }) => {
        const rows: Row[] = values.map((v, id) => ({ id, v }));
        const get = (r: Row) => r.v;
        const sorted = sortRows(rows, { key: "v", direction }, get, () => type);

        // Permutation: same length, same multiset of row references.
        expect(sorted).toHaveLength(rows.length);
        expect([...sorted].sort((a, b) => a.id - b.id)).toEqual(rows);
        sorted.forEach((r) => expect(rows[r.id]).toBe(r));

        // Present keys are ordered; missing keys come last.
        const isMissing = (r: Row) => r.v === null || r.v === undefined;
        const firstMissing = sorted.findIndex(isMissing);
        if (firstMissing >= 0) {
          expect(sorted.slice(firstMissing).every(isMissing)).toBe(true);
        }
        const keyed = sorted.filter((r) => !isMissing(r));
        for (let i = 1; i < keyed.length; i++) {
          const c = cmp[type](keyed[i - 1].v as string | number, keyed[i].v as string | number);
          if (direction === "asc") expect(c).toBeLessThanOrEqual(0);
          else expect(c).toBeGreaterThanOrEqual(0);
        }

        // A null state keeps the input order.
        expect(sortRows(rows, null, get, () => type)).toEqual(rows);
      }),
      { numRuns: 100 },
    );
  });

  // Feature: ui-polish-and-consistency, Property 19: Sorting is stable
  it("Property 19: Sorting is stable", () => {
    // **Validates: Requirements 20.5**
    type Row = { id: number; v: string | number | null | undefined };

    // Small key pools force many repeated keys. Missing values tie with each other too.
    const pool: Record<SortType, (string | number | null | undefined)[]> = {
      text: ["a", "b", "c", null, undefined],
      number: [1, 2, 3, null, undefined],
      date: ["2024-01-01", "2024-06-15", "2025-03-09", null, undefined],
    };

    const scenarioArb = fc
      .constantFrom<SortType>("text", "number", "date")
      .chain((type) =>
        fc.record({
          type: fc.constant(type),
          direction: directionArb,
          values: fc.array(fc.constantFrom(...pool[type]), { maxLength: 40 }),
        }),
      );

    fc.assert(
      fc.property(scenarioArb, ({ type, direction, values }) => {
        const rows: Row[] = values.map((v, id) => ({ id, v }));
        const sorted = sortRows(rows, { key: "v", direction }, (r) => r.v, () => type);

        // Group by key (null and undefined are both "missing"); within each group
        // the ids must match the input order.
        const keyOf = (r: Row) => (r.v === null || r.v === undefined ? "__missing__" : String(r.v));
        const groupIds = (list: Row[]) => {
          const groups = new Map<string, number[]>();
          for (const r of list) {
            const k = keyOf(r);
            groups.set(k, [...(groups.get(k) ?? []), r.id]);
          }
          return groups;
        };
        const expected = groupIds(rows);
        const actual = groupIds(sorted);

        expect(actual.size).toBe(expected.size);
        for (const [k, ids] of expected) {
          expect(actual.get(k)).toEqual(ids);
        }
      }),
      { numRuns: 100 },
    );
  });

  // Feature: ui-polish-and-consistency, Property 20: Descending reverses ascending when keys are distinct
  it("Property 20: Descending reverses ascending when keys are distinct", () => {
    // **Validates: Requirements 20.6**
    type Row = { id: number; v: string | number };

    const distinct: Record<SortType, fc.Arbitrary<(string | number)[]>> = {
      text: fc.uniqueArray(fc.stringMatching(/^[a-z]{1,6}$/), { maxLength: 30 }),
      number: fc.uniqueArray(fc.integer({ min: -1000, max: 1000 }), { maxLength: 30 }),
      date: fc.uniqueArray(
        fc
          .date({ min: new Date("2000-01-01T00:00:00Z"), max: new Date("2040-12-31T00:00:00Z"), noInvalidDate: true })
          .map((d) => d.toISOString().slice(0, 10)),
        { maxLength: 30 },
      ),
    };

    const scenarioArb = fc
      .constantFrom<SortType>("text", "number", "date")
      .chain((type) => fc.record({ type: fc.constant(type), values: distinct[type] }));

    fc.assert(
      fc.property(scenarioArb, ({ type, values }) => {
        const rows: Row[] = values.map((v, id) => ({ id, v }));
        const get = (r: Row) => r.v;
        const asc = sortRows(rows, { key: "v", direction: "asc" }, get, () => type);
        const desc = sortRows(rows, { key: "v", direction: "desc" }, get, () => type);

        expect(desc).toEqual([...asc].reverse());
      }),
      { numRuns: 100 },
    );
  });
});
