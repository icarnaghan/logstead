import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "../App";
import { ToastProvider } from "../components/ui";
import { ThemeProvider } from "../theme/ThemeProvider";

/**
 * Palette rules (Requirements 17.1, 17.3, 17.4, 25.3).
 *
 * The codebase-wide bans (hex / rgb() colors, raw Tailwind palette utilities,
 * text-brand-orange, amber/gold text, text-fg-subtle on bg-accent-subtle) are
 * enforced by `no-restricted-syntax` selectors in `eslint.config.js`, which run
 * in `npx eslint .`. Exceptions (tests, `src/test/`, `src/components/brand/`)
 * are listed there too.
 *
 * This file keeps the one palette check that is about a rendered element.
 */
describe("palette rules (rendered)", () => {
  it("skip link uses outline-accent-fg", () => {
    render(
      <ThemeProvider><ToastProvider>
        <MemoryRouter initialEntries={["/"]}>
          <App />
        </MemoryRouter>
      </ToastProvider></ThemeProvider>,
    );
    const link = screen.getByRole("link", { name: /skip to main content/i });
    expect(link).toHaveAttribute("href", "#main-content");
    expect(link.className).toContain("outline-accent-fg");
  });
});
