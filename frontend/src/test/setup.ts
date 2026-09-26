import "@testing-library/jest-dom/vitest";
import { afterEach, expect } from "vitest";
import { cleanup } from "@testing-library/react";
import * as axeMatchers from "vitest-axe/matchers";
import "vitest-axe/extend-expect";

// Register the vitest-axe custom matchers (e.g. `toHaveNoViolations`) so
// component tests can run automated accessibility checks (Requirement 14.4).
expect.extend(axeMatchers);

// Recharts' <ResponsiveContainer> observes its element with ResizeObserver,
// which jsdom does not implement. Register a no-op stub so charts can mount in
// tests without throwing (Requirement 15.1). Only installed when absent so a
// richer polyfill in another environment is left intact.
if (typeof globalThis.ResizeObserver === "undefined") {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  globalThis.ResizeObserver =
    ResizeObserverStub as unknown as typeof ResizeObserver;
  if (typeof window !== "undefined") {
    window.ResizeObserver =
      ResizeObserverStub as unknown as typeof ResizeObserver;
  }
}

// Unmount React trees after each test to avoid cross-test leakage.
afterEach(() => {
  cleanup();
});
