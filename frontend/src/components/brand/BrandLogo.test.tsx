import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BrandLogo } from "./BrandLogo";

vi.mock("./Logo", () => ({
  Logo: () => {
    throw new Error("artwork failed");
  },
}));

describe("BrandLogo error boundary", () => {
  afterEach(() => vi.restoreAllMocks());

  it("falls back to WordmarkFallback when Logo throws", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
    render(<BrandLogo />);
    const el = screen.getByRole("img", { name: "Logstead" });
    expect(el).toHaveTextContent("logstead");
    expect(el).toHaveClass("text-fg");
  });

  it("keeps the fallback decorative when requested", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
    render(<BrandLogo decorative />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("logstead")).toHaveAttribute("aria-hidden", "true");
  });
});
