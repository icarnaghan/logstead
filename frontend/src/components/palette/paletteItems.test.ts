import { describe, expect, it } from "vitest";
import { buildLocalItems } from "./paletteItems";

describe("buildLocalItems: Activity destination", () => {
  it("lists exactly one Activity page destination", () => {
    const items = buildLocalItems({
      properties: [],
      years: [],
      currentPropertyId: null,
      platform: "other",
      hasProperty: false,
    });
    const activity = items.filter(
      (i) => i.kind === "destination" && i.to === "/activity",
    );
    expect(activity).toHaveLength(1);
    expect(activity[0]).toMatchObject({ label: "Activity", group: "Pages" });
  });
});
