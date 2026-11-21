import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { usePropertyYearRange } from "./usePropertyYearRange";
import { latestCompletedTaxYear } from "./taxYears";

const NO_ASSETS: readonly { placed_in_service_date: string }[] = [];

describe("usePropertyYearRange", () => {
  it("extends the range back to the loaded earliest data year", async () => {
    const load = vi.fn().mockResolvedValue(2010);
    const { result } = renderHook(() =>
      usePropertyYearRange("p1", NO_ASSETS, load),
    );

    await waitFor(() => {
      expect(result.current[result.current.length - 1]).toBe(2010);
    });
    expect(result.current[0]).toBe(latestCompletedTaxYear());
    expect(load).toHaveBeenCalledWith("p1", expect.any(AbortSignal));
  });

  it("falls back to the assets-only range when the loader rejects", async () => {
    const load = vi.fn().mockRejectedValue(new Error("boom"));
    const assets = [{ placed_in_service_date: "2012-03-01" }];
    const { result } = renderHook(() => usePropertyYearRange("p1", assets, load));

    await waitFor(() => expect(load).toHaveBeenCalled());
    expect(result.current[result.current.length - 1]).toBe(2012);
    expect(result.current[0]).toBe(latestCompletedTaxYear());
  });

  it("refetches when the property changes", async () => {
    const load = vi.fn(async (id: string) => (id === "p1" ? 2010 : 2014));
    const { result, rerender } = renderHook(
      ({ id }: { id: string }) => usePropertyYearRange(id, NO_ASSETS, load),
      { initialProps: { id: "p1" } },
    );
    await waitFor(() => {
      expect(result.current[result.current.length - 1]).toBe(2010);
    });

    rerender({ id: "p2" });

    await waitFor(() => {
      expect(result.current[result.current.length - 1]).toBe(2014);
    });
    expect(load).toHaveBeenCalledTimes(2);
    expect(load.mock.calls[1][0]).toBe("p2");
  });
});
