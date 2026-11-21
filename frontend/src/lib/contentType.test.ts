import { describe, expect, it } from "vitest";
import { contentTypeFromFilename, resolveContentType } from "./contentType";

const ALLOWED = ["application/pdf", "image/jpeg", "image/heic"];

describe("contentTypeFromFilename", () => {
  it("maps known extensions case-insensitively", () => {
    expect(contentTypeFromFilename("a.PDF")).toBe("application/pdf");
    expect(contentTypeFromFilename("a.b.JPG")).toBe("image/jpeg");
    expect(contentTypeFromFilename("a.heif")).toBe("image/heif");
  });
  it("returns empty for unknown or missing extensions", () => {
    expect(contentTypeFromFilename("a.gif")).toBe("");
    expect(contentTypeFromFilename("noext")).toBe("");
  });
});

describe("resolveContentType", () => {
  it("uses the browser type when allowed", () => {
    expect(resolveContentType({ name: "x", type: "image/jpeg" }, ALLOWED)).toBe(
      "image/jpeg",
    );
  });
  it("infers from the extension when the type is empty", () => {
    expect(resolveContentType({ name: "x.heic", type: "" }, ALLOWED)).toBe(
      "image/heic",
    );
  });
  it("returns null for disallowed or unknown types", () => {
    expect(resolveContentType({ name: "x.exe", type: "" }, ALLOWED)).toBeNull();
    expect(
      resolveContentType({ name: "x.pdf", type: "text/html" }, ALLOWED),
    ).toBeNull();
    expect(resolveContentType({ name: "x.png", type: "" }, ALLOWED)).toBeNull();
  });
});
