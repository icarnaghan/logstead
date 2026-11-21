import { act, renderHook } from "@testing-library/react";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { useAsyncResource } from "./useAsyncResource";

describe("useAsyncResource properties", () => {
  // **Validates: Requirements R3 (stale results never overwrite newer loads)**
  it("settles on the newest key's result regardless of response order", async () => {
    await fc.assert(
      fc.asyncProperty(
          fc.integer({ min: 2, max: 6 }).chain((n) =>
            fc.shuffledSubarray(
              Array.from({ length: n }, (_, i) => i),
              { minLength: n, maxLength: n },
            ),
          ),
          async (order) => {
            const n = order.length;
            const resolvers: Array<(v: string) => void> = [];
            const signals: AbortSignal[] = [];
            const loader = (signal: AbortSignal) => {
              signals.push(signal);
              return new Promise<string>((resolve) => {
                resolvers.push(resolve);
              });
            };
            const { result, rerender, unmount } = renderHook(
              ({ key }: { key: number }) =>
                useAsyncResource(loader, { deps: [key] }),
              { initialProps: { key: 0 } },
            );
            for (let k = 1; k < n; k++) rerender({ key: k });
            for (const idx of order) {
              await act(async () => {
                resolvers[idx](`v${idx}`);
                await Promise.resolve();
              });
            }
            // Every load but the newest was aborted.
            expect(signals.slice(0, -1).every((s) => s.aborted)).toBe(true);
            expect(result.current.data).toBe(`v${n - 1}`);
            expect(result.current.status).toBe("success");
            unmount();
          },
      ),
      { numRuns: 25 },
    );
  });
});
