import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AnchorYearNotice } from "./AnchorYearNotice";
import { EstimateNotice } from "./EstimateNotice";

afterEach(cleanup);

describe("AnchorYearNotice", () => {
  it("states the anchor year, the partial-year scope, and the 1098 instruction", () => {
    render(<AnchorYearNotice anchorDate="2025-06-01" />);
    const note = screen.getByRole("note");
    expect(note.textContent).toContain("Anchor year: 2025");
    expect(note.textContent).toContain("only payments after the anchor date (2025-06-01)");
    expect(note.textContent).toContain("Form 1098");
    expect(note.textContent).toContain("for 2025 and for earlier years");
  });
});

describe("EstimateNotice", () => {
  it("mentions the anchor and Form 1098", () => {
    render(<EstimateNotice />);
    const note = screen.getByRole("note");
    expect(note.textContent).toContain("anchor");
    expect(note.textContent).toContain("Form 1098");
  });
});
