import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { formatDocumentTitle, useDocumentTitle } from "./useDocumentTitle";

/** Requirements 5.1, 5.2 */
describe("useDocumentTitle", () => {
  beforeEach(() => {
    document.title = "Logstead";
  });
  afterEach(() => {
    document.title = "";
  });

  it("formats the title as '{page} - Logstead'", () => {
    renderHook(() => useDocumentTitle("Dashboard"));
    expect(document.title).toBe("Dashboard - Logstead");
  });

  it("falls back to the app name when the title is empty", () => {
    expect(formatDocumentTitle("  ")).toBe("Logstead");
    expect(formatDocumentTitle(null)).toBe("Logstead");
  });

  it("restores the previous title on unmount", () => {
    document.title = "Previous";
    const { unmount } = renderHook(() => useDocumentTitle("Properties"));
    expect(document.title).toBe("Properties - Logstead");
    unmount();
    expect(document.title).toBe("Previous");
  });

  it("updates the title when it changes while mounted", () => {
    const { rerender, unmount } = renderHook(
      ({ title }) => useDocumentTitle(title),
      { initialProps: { title: "One" } },
    );
    expect(document.title).toBe("One - Logstead");
    rerender({ title: "Two" });
    expect(document.title).toBe("Two - Logstead");
    unmount();
    expect(document.title).toBe("Logstead");
  });
});
