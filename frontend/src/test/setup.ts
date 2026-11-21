import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, expect } from "vitest";
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

// jsdom lacks the pointer-capture APIs that Radix primitives call on pointer
// events. Guarded so a real implementation is never overridden.
if (typeof Element !== "undefined" && !Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}

// jsdom lacks matchMedia (Radix Toast reads it for reduced-motion). Default to
// "no match"; tests that need a specific value stub it locally.
if (typeof window !== "undefined" && !window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

// The test env's built-in localStorage is not reliably usable, so every test
// starts with a fresh in-memory Storage replacement.
function installMemoryLocalStorage(): void {
  const data = new Map<string, string>();
  const mock = {
    getItem: (k: string) => (data.has(k) ? data.get(k)! : null),
    setItem: (k: string, v: string) => void data.set(k, String(v)),
    removeItem: (k: string) => void data.delete(k),
    clear: () => data.clear(),
    key: (i: number) => Array.from(data.keys())[i] ?? null,
    get length() {
      return data.size;
    },
  };
  Object.defineProperty(window, "localStorage", {
    value: mock,
    configurable: true,
    writable: true,
  });
}

beforeEach(() => {
  installMemoryLocalStorage();
});

// Unmount React trees after each test to avoid cross-test leakage.
afterEach(() => {
  cleanup();
});
