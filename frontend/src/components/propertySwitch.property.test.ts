import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { PROPERTY_NAV, propertyPath } from "./navConfig";
import {
  propertyIdFromPath,
  sectionFromPath,
  switchPropertyPath,
} from "./propertySwitch";

const segments = PROPERTY_NAV.map((item) => item.segment);
const search = fc.constantFrom("", "?year=2024", "?year=2023&x=1", "?x=1");

describe("propertySwitch (property tests)", () => {
  // Feature: ui-polish-and-consistency, Property 14: Switching property keeps the section
  // **Validates: Requirements 19.3, 19.6**
  it("Property 14: switching property keeps the section", () => {
    fc.assert(
      fc.property(
        fc.uuid(),
        fc.uuid(),
        fc.constantFrom(...segments),
        search,
        (oldId, newId, segment, s) => {
          const pathname = propertyPath(oldId, segment);
          const result = switchPropertyPath(pathname, s, newId);
          const resultPath = result.split("?")[0];
          expect(sectionFromPath(resultPath)).toBe(segment);
          expect(propertyIdFromPath(resultPath)).toBe(newId);
        },
      ),
      { numRuns: 100 },
    );
  });

  // Feature: ui-polish-and-consistency, Property 15: Switching from a non-property route goes to the overview
  // **Validates: Requirements 19.4**
  it("Property 15: switching from a non-property route goes to the overview", () => {
    const nonPropertyPath = fc
      .oneof(
        fc.constantFrom("/", "/dashboard", "/settings", "/properties", "/properties/"),
        fc
          .array(fc.stringMatching(/^[a-z0-9-]{1,12}$/), { minLength: 1, maxLength: 4 })
          .map((parts) => `/${parts.join("/")}`),
      )
      .filter((p) => propertyIdFromPath(p) === null);

    fc.assert(
      fc.property(nonPropertyPath, fc.uuid(), (pathname, id) => {
        expect(switchPropertyPath(pathname, "", id)).toBe(propertyPath(id, ""));
      }),
      { numRuns: 100 },
    );
  });

  // Feature: ui-polish-and-consistency, Property 16: Only the year parameter is carried over
  // **Validates: Requirements 19.7**
  it("Property 16: only the year parameter is carried over", () => {
    const param = fc.tuple(
      fc.constantFrom("year", "x", "month", "q", "page"),
      fc.string({ minLength: 1, maxLength: 12 }),
    );

    fc.assert(
      fc.property(
        fc.uuid(),
        fc.array(param, { maxLength: 6 }),
        fc.constantFrom("/", "/settings", ...segments.map((s) => `/properties/p1/${s}`)),
        (id, params, pathname) => {
          const query = new URLSearchParams();
          for (const [k, v] of params) query.append(k, v);

          const result = switchPropertyPath(pathname, `?${query.toString()}`, id);
          const [, resultQuery = ""] = result.split("?");
          const out = new URLSearchParams(resultQuery);
          const expectedYear = query.get("year");

          if (expectedYear === null) {
            expect(result).not.toContain("?");
          } else {
            expect(out.get("year")).toBe(expectedYear);
            expect(Array.from(out.keys())).toEqual(["year"]);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
