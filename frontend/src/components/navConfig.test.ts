import { describe, expect, it } from "vitest";
import {
  IMPORT_NAV,
  NAV_GROUPS,
  PRIMARY_NAV,
  PROPERTY_NAV,
  propertyPath,
} from "./navConfig";

/** Validates: Requirements 18.1, 18.2 */
describe("NAV_GROUPS", () => {
  it("defines Portfolio, Tax and Tools groups with the expected items in order", () => {
    expect(
      NAV_GROUPS.map((g) => [g.id, g.label, g.items.map((i) => i.label)]),
    ).toEqual([
      ["portfolio", "Portfolio", ["Dashboard", "Properties", "Businesses"]],
      ["tax", "Tax", ["Reports", "Carryforward", "Accountant package"]],
      ["tools", "Tools", ["Import", "Activity"]],
    ]);
  });

  it("gives every item an icon and flattens to PRIMARY_NAV in the same order", () => {
    expect(NAV_GROUPS.flatMap((g) => g.items)).toEqual(PRIMARY_NAV);
    for (const item of PRIMARY_NAV) expect(item.icon).toBeDefined();
  });
});

/**
 * Primary navigation model (passive-loss-carryforward: nav wiring). Pins the
 * top-level destinations and ordering, including the Carryforward entry, so the
 * nav and the route table stay in sync.
 */
describe("PRIMARY_NAV", () => {
  it("lists the top-level destinations in the expected order", () => {
    expect(PRIMARY_NAV.map((item) => [item.to, item.label])).toEqual([
      ["/", "Dashboard"],
      ["/properties", "Properties"],
      ["/businesses", "Businesses"],
      ["/reports", "Reports"],
      ["/carryforward", "Carryforward"],
      ["/accountant-package", "Accountant package"],
      ["/imports/schedule-e", "Import"],
      ["/activity", "Activity"],
    ]);
  });

  it("no longer lists the old import labels", () => {
    const labels = PRIMARY_NAV.map((item) => item.label);
    expect(labels).not.toContain("Import Schedule E");
    expect(labels).not.toContain("Import from PDF");
  });

  it("has a single Import entry without an exact-match flag", () => {
    const entry = PRIMARY_NAV.find((item) => item.label === "Import");
    expect(entry?.end).toBeUndefined();
  });

  it("includes the Carryforward destination", () => {
    expect(PRIMARY_NAV).toContainEqual({
      to: "/carryforward",
      label: "Carryforward",
      icon: "carryforward",
    });
  });
});

describe("IMPORT_NAV", () => {
  it("lists Enter manually (exact) then Upload PDF", () => {
    expect(IMPORT_NAV).toEqual([
      { to: "/imports/schedule-e", label: "Enter manually", end: true },
      { to: "/imports/schedule-e/extract", label: "Upload PDF" },
    ]);
  });
});

/**
 * Unit tests for the per-property navigation model (task 1.1).
 *
 * Verifies the Overview-first ordering, the exact section labels, and the
 * clean property index path produced by `propertyPath` (no trailing slash).
 *
 * Validates: Requirements 2.1, 2.2
 */

describe("PROPERTY_NAV", () => {
  it("leads with the Overview index entry (exact match)", () => {
    expect(PROPERTY_NAV[0]).toEqual({
      segment: "",
      label: "Overview",
      end: true,
    });
  });

  it("lists the sub-sections in the expected order", () => {
    expect(PROPERTY_NAV.map((item) => item.label)).toEqual([
      "Overview",
      "Transactions",
      "Repairs",
      "Depreciable Assets",
      "Loans",
      "Schedule E Report",
      "Checklist",
    ]);
  });

  it("marks only the Overview entry as an exact match", () => {
    for (const item of PROPERTY_NAV) {
      if (item.segment === "") {
        expect(item.end).toBe(true);
      } else {
        expect(item.end).toBeUndefined();
      }
    }
  });
});

describe("propertyPath", () => {
  it("returns the clean property index path for an empty segment", () => {
    expect(propertyPath("p1", "")).toBe("/properties/p1");
  });

  it("appends non-empty segments to the property path", () => {
    expect(propertyPath("p1", "transactions")).toBe(
      "/properties/p1/transactions",
    );
  });
});
