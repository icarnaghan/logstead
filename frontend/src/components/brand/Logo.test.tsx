import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { Logo } from "./Logo";
import { WordmarkFallback } from "./WordmarkFallback";

/** Branding tests: Logo and WordmarkFallback (Requirements 15, 16). */
describe("Logo", () => {
  it("exposes role img named Logstead by default", () => {
    render(<Logo />);
    expect(screen.getByRole("img", { name: "Logstead" })).toBeInTheDocument();
  });

  it("is hidden from assistive tech when decorative", () => {
    const { container } = render(<Logo decorative />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).not.toHaveAttribute("role");
    expect(svg).not.toHaveAttribute("aria-label");
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("renders the tagline only when requested, with the brand-tagline fill class", () => {
    const { container, rerender } = render(<Logo />);
    expect(container.querySelector(".fill-brand-tagline")).toBeNull();
    rerender(<Logo tagline />);
    expect(container.querySelectorAll(".fill-brand-tagline")).toHaveLength(1);
  });

  it("uses unique gradient ids across two instances and references them", () => {
    const { container } = render(
      <>
        <Logo />
        <Logo />
      </>,
    );
    const ids = Array.from(container.querySelectorAll("linearGradient")).map((g) => g.id);
    expect(ids.length).toBeGreaterThan(0);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) {
      expect(id).toMatch(/^[A-Za-z0-9_-]+$/);
      expect(container.innerHTML).toContain(`url(#${id})`);
    }
  });

  it("reserves its box with an aspect-ratio", () => {
    const { container } = render(<Logo />);
    expect(container.querySelector("svg")!.style.aspectRatio).toMatch(/^\d+(\.\d+)? \/ \d+(\.\d+)?$/);
  });

  it("fills the wordmark with currentColor", () => {
    const { container } = render(<Logo />);
    expect(container.querySelector('path[fill="currentColor"]')).not.toBeNull();
  });

  it("has no axe violations", async () => {
    const { container } = render(<Logo tagline />);
    expect(await axe(container, { rules: { "color-contrast": { enabled: false } } })).toHaveNoViolations();
  });
});

describe("WordmarkFallback", () => {
  it("is named Logstead, uses text-fg, and has no amber or gold classes", () => {
    render(<WordmarkFallback />);
    const el = screen.getByRole("img", { name: "Logstead" });
    expect(el).toHaveClass("text-fg");
    expect(el.className).not.toMatch(/amber|gold/);
  });
});
