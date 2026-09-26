import "vitest";
import type { AxeResults } from "axe-core";

/**
 * Type augmentation for the `vitest-axe` `toHaveNoViolations` matcher.
 *
 * The runtime matcher is registered in `src/test/setup.ts` via
 * `expect.extend(axeMatchers)`. However, `vitest-axe@0.1.0` ships its type
 * augmentation against the legacy `namespace Vi { interface Assertion }`, which
 * Vitest 3 no longer uses (the matcher interface now lives on `Assertion` in
 * the `vitest` module). As a result `tsc -b` cannot see `toHaveNoViolations`.
 *
 * This declaration re-augments the current Vitest `Assertion` interface so the
 * matcher is visible to the type-checker across the project, matching the
 * runtime behavior. It does not weaken any strictness settings.
 */
declare module "vitest" {
  interface Assertion<T = any> {
    toHaveNoViolations(): T;
  }
  interface AsymmetricMatchersContaining {
    toHaveNoViolations(): void;
  }
}

// Ensure `AxeResults` stays referenced so the import isn't elided; the matcher
// is only meaningful when asserting on an axe results object.
export type { AxeResults };
