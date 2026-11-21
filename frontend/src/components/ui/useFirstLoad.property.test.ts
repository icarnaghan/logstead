import { renderHook } from "@testing-library/react";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { deriveLoadView, useFirstLoad } from "./useFirstLoad";

type Obs = { loading: boolean; error: string | null };

const observation: fc.Arbitrary<Obs> = fc.record({
  loading: fc.boolean(),
  error: fc.option(fc.string({ minLength: 1 }), { nil: null }),
});

const sequence = fc.array(observation, { minLength: 1, maxLength: 30 });

describe("useFirstLoad properties", () => {
  // Feature: ui-polish-and-consistency, Property 12: Content stays mounted once loaded
  // **Validates: Requirements 14.1, 14.2, 14.8, 23.5**
  it("keeps content mounted once loaded and derives skeleton/stale error", () => {
    fc.assert(
      fc.property(sequence, (obs) => {
        const { result, rerender } = renderHook((p: Obs) => useFirstLoad(p), {
          initialProps: obs[0],
        });
        let loadedYet = false;
        obs.forEach((o, i) => {
          if (i > 0) rerender(o);
          const view = result.current;
          if (!o.loading && o.error === null) loadedYet = true;

          expect(view.showSkeleton).toBe(!loadedYet && o.error === null);
          expect(view.showContent).toBe(loadedYet);
          expect(view.showError).toBe(o.error !== null);
          expect(view.errorIsStale).toBe(loadedYet && o.error !== null);
          expect(view.refreshing).toBe(loadedYet && o.loading);
        });
      }),
      { numRuns: 100 },
    );
  });

  it("returns to the never-loaded state when resetKey changes", () => {
    fc.assert(
      fc.property(sequence, (obs) => {
        const { result, rerender } = renderHook(
          (p: Obs & { key: number }) => useFirstLoad({ ...p, resetKey: p.key }),
          { initialProps: { ...obs[0], key: 0 } },
        );
        obs.forEach((o, i) => {
          if (i > 0) rerender({ ...o, key: 0 });
        });
        // Change key with a still-loading, error-free observation.
        rerender({ loading: true, error: null, key: 1 });
        expect(result.current).toEqual(
          deriveLoadView({ hasLoaded: false, loading: true, error: null }),
        );
        expect(result.current.showSkeleton).toBe(true);
        expect(result.current.showContent).toBe(false);
      }),
      { numRuns: 100 },
    );
  });
});
