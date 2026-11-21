import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { PROPERTY_NAV, propertyPath } from "../components/navConfig";
import { currentSection } from "./propertySections";

const propertyId = fc.stringMatching(/^[A-Za-z0-9_-]{1,36}$/);

// Feature: ui-polish, Property 27: Section resolver round trip
describe("currentSection property", () => {
  it("returns the nav entry for every section path, with or without a trailing slash", () => {
    // **Validates: Requirements 21.8, 21.9**
    fc.assert(
      fc.property(
        propertyId,
        fc.constantFrom(...PROPERTY_NAV),
        fc.boolean(),
        (id, item, slash) => {
          const base = propertyPath(id, item.segment);
          expect(currentSection(base, id)).toBe(item);
          if (slash) expect(currentSection(`${base}/`, id)).toBe(item);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("returns null for any path outside the property", () => {
    // **Validates: Requirements 21.8, 21.9**
    const outside = fc
      .tuple(propertyId, propertyId, fc.array(fc.stringMatching(/^[a-z0-9]{1,8}$/), { maxLength: 3 }))
      .map(([id, other, rest]) => ({ id, path: ["", "other", other, ...rest].join("/") }))
      .filter(({ id, path }) => path !== `/properties/${id}` && !path.startsWith(`/properties/${id}/`));
    const otherProperty = fc
      .tuple(propertyId, propertyId, fc.constantFrom(...PROPERTY_NAV))
      .filter(([a, b]) => a !== b)
      .map(([id, other, item]) => ({ id, path: propertyPath(other, item.segment) }));
    fc.assert(
      fc.property(fc.oneof(outside, otherProperty), ({ id, path }) => {
        expect(currentSection(path, id)).toBeNull();
      }),
      { numRuns: 100 },
    );
  });
});
