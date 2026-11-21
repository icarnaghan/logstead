import { describe, expect, it } from "vitest";
import { findDuplicates, formatKeys, SHORTCUTS } from "./registry";

describe("shortcut registry", () => {
  it("has no duplicate key combinations", () => {
    expect(findDuplicates(SHORTCUTS)).toEqual([]);
  });

  it("gives every entry a label and a group", () => {
    for (const def of SHORTCUTS) {
      expect(def.label.trim()).not.toBe("");
      expect(def.group.trim()).not.toBe("");
    }
  });

  it("registers g a for Activity", () => {
    const def = SHORTCUTS.find((d) => d.id === "go-activity");
    expect(def?.keys).toEqual(["g", "a"]);
    expect(def?.group).toBe("Go to");
  });
  it("detects duplicates", () => {
    expect(findDuplicates([SHORTCUTS[0], SHORTCUTS[0]])).toEqual(["mod+k"]);
  });

  it("formats mod per platform", () => {
    expect(formatKeys(SHORTCUTS[0], "mac")).toEqual(["Cmd", "K"]);
    expect(formatKeys(SHORTCUTS[0], "other")).toEqual(["Ctrl", "K"]);
  });
});
