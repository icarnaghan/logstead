import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { usePortfolioYearRange } from "./usePortfolioYearRange";
import { latestCompletedTaxYear } from "./taxYears";
import type { Property } from "../api/properties";

const props = (...ids: string[]) =>
  ids.map((id) => ({ id }) as unknown as Property);

describe("usePortfolioYearRange", () => {
  it("starts at the earliest year across all properties", async () => {
    const earliest: Record<string, number | null> = { a: 2014, b: 2010 };
    const loadEarliest = vi.fn(async (id: string) => earliest[id]);
    const { result } = renderHook(() =>
      usePortfolioYearRange(async () => props("a", "b"), loadEarliest),
    );

    await waitFor(() => {
      expect(result.current[result.current.length - 1]).toBe(2010);
    });
    expect(result.current[0]).toBe(latestCompletedTaxYear());
    expect(loadEarliest).toHaveBeenCalledTimes(2);
  });

  it("ignores properties with no activity and tolerates a failed lookup", async () => {
    const loadEarliest = vi.fn(async (id: string) => {
      if (id === "a") return null;
      if (id === "b") throw new Error("boom");
      return 2012;
    });
    const { result } = renderHook(() =>
      usePortfolioYearRange(async () => props("a", "b", "c"), loadEarliest),
    );

    await waitFor(() => {
      expect(result.current[result.current.length - 1]).toBe(2012);
    });
  });

  it("falls back to the recent-years window when the property list fails", async () => {
    const loadProperties = vi.fn().mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => usePortfolioYearRange(loadProperties));

    await waitFor(() => expect(loadProperties).toHaveBeenCalled());
    const latest = latestCompletedTaxYear();
    expect(result.current).toEqual([
      latest,
      latest - 1,
      latest - 2,
      latest - 3,
      latest - 4,
      latest - 5,
    ]);
  });
});
