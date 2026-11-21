import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Spinner } from "./Spinner";

/** Unit tests for Spinner (task 2.2, Requirement 3.1). */
describe("Spinner", () => {
  it("is decorative: hidden from assistive tech and not focusable", () => {
    const { container } = render(<Spinner />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("focusable", "false");
  });

  it("spins, inherits currentColor, and merges className", () => {
    const { container } = render(<Spinner className="h-6 w-6" />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveClass("animate-spin", "h-6", "w-6");
    expect(container.querySelector('[stroke="currentColor"]')).not.toBeNull();
  });
});
