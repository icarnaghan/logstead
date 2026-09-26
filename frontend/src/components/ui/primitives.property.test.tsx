import { render } from "@testing-library/react";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { Button, Input, Select, FOCUS_RING } from "./index";

/**
 * Property-based test for the shared UI primitives (task 3.12).
 *
 * Complements the example-based unit tests in `Button.test.tsx`,
 * `Input.test.tsx`, and `Select.test.tsx` by asserting a universal property
 * across many generated prop combinations.
 */

// Feature: ui-polish-and-visualizations, Property 5: Every focusable primitive is consistently focus-ringed and token-colored

/** Every class the canonical focus ring is composed of. */
const FOCUS_RING_CLASSES = FOCUS_RING.split(" ").filter(Boolean);

/**
 * Raw Tailwind color-palette prefixes that must never appear on a token-only
 * primitive. Semantic token classes (e.g. `bg-accent`, `text-fg`,
 * `border-danger`) carry no palette scale, so any of these prefixes signals a
 * hardcoded color leak.
 */
const RAW_PALETTE_PREFIXES = [
  "slate",
  "gray",
  "zinc",
  "neutral",
  "stone",
  "red",
  "orange",
  "amber",
  "yellow",
  "lime",
  "green",
  "emerald",
  "teal",
  "cyan",
  "sky",
  "blue",
  "indigo",
  "violet",
  "purple",
  "fuchsia",
  "pink",
  "rose",
];

const HEX_COLOR = /#[0-9a-fA-F]{3,8}/;
const RGB_COLOR = /rgba?\(/;

/**
 * Assert a focusable element carries the full canonical focus ring and uses
 * only semantic-token colors (no hex, no `rgb(...)`, no raw palette prefixes).
 */
function assertFocusRingedAndTokenColored(element: HTMLElement, label: string) {
  const className = element.className;

  // 1. Every canonical focus-ring class is present.
  for (const cls of FOCUS_RING_CLASSES) {
    expect(className.split(/\s+/), `${label}: missing focus-ring class "${cls}"`).toContain(cls);
  }

  // 2. No hardcoded colors.
  expect(HEX_COLOR.test(className), `${label}: hardcoded hex color in "${className}"`).toBe(false);
  expect(RGB_COLOR.test(className), `${label}: literal rgb()/rgba() in "${className}"`).toBe(false);

  // 3. No raw Tailwind palette color classes (e.g. bg-slate-200, text-red-500).
  const tokens = className.split(/\s+/).filter(Boolean);
  for (const token of tokens) {
    // Strip any variant prefixes (hover:, focus-visible:, dark:, etc.).
    const utility = token.slice(token.lastIndexOf(":") + 1);
    for (const palette of RAW_PALETTE_PREFIXES) {
      const rawPattern = new RegExp(`-${palette}-\\d`);
      expect(
        rawPattern.test(utility),
        `${label}: raw palette color class "${token}"`,
      ).toBe(false);
    }
  }
}

/** Arbitrary over the focusable primitives and their varying props. */
const primitiveArb = fc.oneof(
  fc.record({
    kind: fc.constant("button" as const),
    variant: fc.constantFrom("primary", "secondary", "danger") as fc.Arbitrary<
      "primary" | "secondary" | "danger"
    >,
    size: fc.constantFrom("sm", "md") as fc.Arbitrary<"sm" | "md">,
    disabled: fc.boolean(),
  }),
  fc.record({
    kind: fc.constant("input" as const),
    invalid: fc.boolean(),
  }),
  fc.record({
    kind: fc.constant("select" as const),
    invalid: fc.boolean(),
  }),
);

describe("Property 5: Every focusable primitive is consistently focus-ringed and token-colored", () => {
  it("renders every focusable primitive with the canonical focus ring and token-only colors", () => {
    fc.assert(
      fc.property(primitiveArb, (spec) => {
        let element: HTMLElement;
        let unmount: () => void;

        if (spec.kind === "button") {
          const result = render(
            <Button variant={spec.variant} size={spec.size} disabled={spec.disabled}>
              Action
            </Button>,
          );
          unmount = result.unmount;
          element = result.container.querySelector("button") as HTMLElement;
        } else if (spec.kind === "input") {
          const result = render(<Input invalid={spec.invalid} aria-label="field" />);
          unmount = result.unmount;
          element = result.container.querySelector("input") as HTMLElement;
        } else {
          const result = render(
            <Select invalid={spec.invalid} aria-label="choice">
              <option value="a">A</option>
            </Select>,
          );
          unmount = result.unmount;
          element = result.container.querySelector("select") as HTMLElement;
        }

        try {
          expect(element, `${spec.kind}: focusable element not rendered`).not.toBeNull();
          assertFocusRingedAndTokenColored(element, spec.kind);
        } finally {
          unmount();
        }
      }),
      { numRuns: 100 },
    );
  });
});
