import { describe, expect, it } from "vitest";
import { actionLabel, entityLabel, eventLink } from "./activityText";

describe("activityText", () => {
  it("labels every action and entity", () => {
    expect(actionLabel("create")).toBe("Created");
    expect(actionLabel("restore")).toBe("Restored");
    expect(entityLabel("itemized_entry")).toBe("Repair entry");
    expect(entityLabel("schedule_e")).toBe("Schedule E");
  });

  it("links records to their page with focus", () => {
    const base = { action: "update", record_id: "r1", property_id: "p1" } as const;
    expect(eventLink({ ...base, entity: "transaction" })).toBe(
      "/properties/p1/transactions?focus=r1",
    );
    expect(eventLink({ ...base, entity: "itemized_entry" })).toBe(
      "/properties/p1/repairs?focus=r1",
    );
    expect(eventLink({ ...base, entity: "asset" })).toBe(
      "/properties/p1/assets?focus=r1",
    );
    expect(eventLink({ ...base, entity: "loan" })).toBe(
      "/properties/p1/loans?focus=r1",
    );
    expect(eventLink({ ...base, entity: "property" })).toBe(
      "/properties?focus=r1",
    );
  });

  it("returns null for deletes, missing ids and entities without a page", () => {
    const base = { record_id: "r1", property_id: "p1" };
    expect(eventLink({ ...base, action: "delete", entity: "asset" })).toBeNull();
    expect(
      eventLink({ ...base, record_id: null, action: "create", entity: "asset" }),
    ).toBeNull();
    expect(
      eventLink({ ...base, action: "import", entity: "schedule_e" }),
    ).toBeNull();
    expect(
      eventLink({ ...base, property_id: null, action: "create", entity: "loan" }),
    ).toBeNull();
  });
});
