import { render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RefreshingIndicator } from "./RefreshingIndicator";
import { useFirstLoad } from "./useFirstLoad";

type P = { loading: boolean; error: string | null; resetKey?: unknown };

function setup(initial: P) {
  return renderHook((p: P) => useFirstLoad(p), { initialProps: initial });
}

describe("useFirstLoad", () => {
  it("shows skeleton before the first load completes (14.1)", () => {
    const { result } = setup({ loading: true, error: null });
    expect(result.current.showSkeleton).toBe(true);
    expect(result.current.showContent).toBe(false);
  });

  it("keeps content mounted and marks refreshing on reload (14.2, 14.3)", () => {
    const { result, rerender } = setup({ loading: true, error: null });
    rerender({ loading: false, error: null });
    expect(result.current.showContent).toBe(true);
    rerender({ loading: true, error: null });
    expect(result.current.showContent).toBe(true);
    expect(result.current.showSkeleton).toBe(false);
    expect(result.current.refreshing).toBe(true);
  });

  it("shows stale error over retained content after first load (14.5)", () => {
    const { result, rerender } = setup({ loading: false, error: null });
    rerender({ loading: false, error: "boom" });
    expect(result.current.showContent).toBe(true);
    expect(result.current.showError).toBe(true);
    expect(result.current.errorIsStale).toBe(true);
  });

  it("shows error without content on first-load failure (14.5)", () => {
    const { result } = setup({ loading: false, error: "boom" });
    expect(result.current.showError).toBe(true);
    expect(result.current.showContent).toBe(false);
    expect(result.current.showSkeleton).toBe(false);
    expect(result.current.errorIsStale).toBe(false);
  });

  it("returns to first-load state when resetKey changes (14.1)", () => {
    const { result, rerender } = setup({ loading: false, error: null, resetKey: "a" });
    expect(result.current.showContent).toBe(true);
    rerender({ loading: true, error: null, resetKey: "b" });
    expect(result.current.showSkeleton).toBe(true);
    expect(result.current.showContent).toBe(false);
  });
});

describe("RefreshingIndicator", () => {
  it("renders status text (14.3)", () => {
    render(<RefreshingIndicator />);
    expect(screen.getByRole("status").textContent).toContain("Refreshing");
  });
});
