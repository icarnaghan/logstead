import "@testing-library/jest-dom/vitest";
import { afterEach, expect } from "vitest";
import { cleanup } from "@testing-library/react";
import * as axeMatchers from "vitest-axe/matchers";
import "vitest-axe/extend-expect";

// Register the vitest-axe custom matchers (e.g. `toHaveNoViolations`) so
// component tests can run automated accessibility checks (Requirement 14.4).
expect.extend(axeMatchers);

// Unmount React trees after each test to avoid cross-test leakage.
afterEach(() => {
  cleanup();
});
