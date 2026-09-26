import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import App from "../App";

/**
 * Component / accessibility tests for the navigation shell (task 19.3).
 *
 * These cover Requirement 14.1 (consistent navigation structure), 14.2
 * (responsive layout scaffolding + mobile drawer), and 14.4 (WCAG 2.1 AA
 * color-contrast/keyboard-navigation conformance) at the level automated
 * tooling can reach. Full WCAG 2.1 AA conformance still requires manual
 * testing with assistive technologies; automated axe checks and RTL
 * role/landmark/focus assertions catch the machine-detectable subset.
 *
 * The shell also enforces the numbers-and-forms aesthetic: the initial release
 * renders numeric summaries and forms only, with no charts/visualizations, so
 * the layout must contain no chart/canvas/graphic-role elements.
 */
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("AppLayout — landmarks (Req 14.1, 14.4)", () => {
  it("exposes header, primary navigation, and main landmarks with names", () => {
    renderAt("/");

    // header / banner landmark.
    expect(screen.getByRole("banner")).toBeInTheDocument();

    // main landmark that the skip link targets.
    const main = screen.getByRole("main");
    expect(main).toBeInTheDocument();
    expect(main).toHaveAttribute("id", "main-content");

    // Named navigation landmark for the desktop sidebar.
    expect(
      screen.getByRole("navigation", { name: /primary/i }),
    ).toBeInTheDocument();
  });

  it("labels the per-property navigation landmark distinctly", () => {
    renderAt("/properties/abc-123/transactions");

    // Both the primary nav and the per-property nav are present and each has
    // its own accessible name so screen-reader users can tell them apart.
    expect(
      screen.getByRole("navigation", { name: /primary/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: /property sections/i }),
    ).toBeInTheDocument();
  });

  it("makes the skip-to-content link the first focusable element and points it at #main-content", async () => {
    const user = userEvent.setup();
    renderAt("/");

    const skipLink = screen.getByRole("link", {
      name: /skip to main content/i,
    });
    expect(skipLink).toHaveAttribute("href", "#main-content");

    // Tabbing from the document body reaches the skip link first.
    await user.tab();
    expect(skipLink).toHaveFocus();
  });
});

describe("AppLayout — keyboard navigability & focus order (Req 14.4)", () => {
  it("reaches the skip link, then the primary nav links, in order", async () => {
    const user = userEvent.setup();
    renderAt("/");

    const skipLink = screen.getByRole("link", {
      name: /skip to main content/i,
    });
    const dashboardLink = screen.getByRole("link", { name: /dashboard/i });
    const propertiesLink = screen.getByRole("link", { name: /properties/i });

    await user.tab();
    expect(skipLink).toHaveFocus();

    // The mobile menu toggle is `md:hidden` but still in the tab order under
    // jsdom (no viewport media evaluation), so we walk forward until we reach
    // the first nav link rather than asserting an exact index.
    let guard = 0;
    while (!dashboardLink.contains(document.activeElement) && guard < 6) {
      await user.tab();
      guard += 1;
    }
    expect(dashboardLink).toHaveFocus();

    await user.tab();
    expect(propertiesLink).toHaveFocus();
  });

  it("marks the active route's nav link with aria-current=page", () => {
    renderAt("/properties");

    const propertiesLink = screen.getByRole("link", { name: /properties/i });
    expect(propertiesLink).toHaveAttribute("aria-current", "page");

    // A non-active link must not claim to be the current page.
    const dashboardLink = screen.getByRole("link", { name: /dashboard/i });
    expect(dashboardLink).not.toHaveAttribute("aria-current", "page");
  });
});

describe("AppLayout — mobile navigation drawer (Req 14.2, 14.4)", () => {
  it("toggles aria-expanded and controls the dialog when opened via keyboard", async () => {
    const user = userEvent.setup();
    renderAt("/");

    const toggle = screen.getByRole("button", {
      name: /open navigation menu/i,
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls", "mobile-nav");

    // Open via keyboard activation.
    toggle.focus();
    await user.keyboard("{Enter}");

    expect(toggle).toHaveAttribute("aria-expanded", "true");

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("id", "mobile-nav");

    // The drawer contains its own labelled navigation landmark.
    expect(
      within(dialog).getByRole("navigation", { name: /main/i }),
    ).toBeInTheDocument();
  });

  it("traps focus in the dialog and closes it with Escape, restoring aria-expanded", async () => {
    const user = userEvent.setup();
    renderAt("/");

    const toggle = screen.getByRole("button", {
      name: /open navigation menu/i,
    });
    await user.click(toggle);

    const dialog = await screen.findByRole("dialog");
    // Radix moves focus into the dialog on open (focus trap).
    expect(dialog.contains(document.activeElement)).toBe(true);

    await user.keyboard("{Escape}");

    // Dialog is dismissed and the toggle reflects the collapsed state again.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});

describe("AppLayout — numbers-first layout has no charts/visualizations", () => {
  it("renders no canvas, chart/graphics-role, or SVG chart containers", () => {
    const { container } = renderAt("/");

    // No raster chart surfaces.
    expect(container.querySelector("canvas")).toBeNull();

    // No chart libraries mount graphic containers or graphics roles. The one
    // decorative element in the shell (the hamburger icon) is aria-hidden and
    // not a graphics/img role, so no accessible image/graphic role should be
    // present in the numbers-first shell.
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.queryByRole("graphics-document")).toBeNull();

    // Guard against common chart-lib class hooks sneaking into the shell.
    expect(
      container.querySelector(
        '[class*="recharts"], [class*="chartjs"], [class*="chart-container"], [class*="victory"], [class*="nivo"]',
      ),
    ).toBeNull();
  });
});

describe("AppLayout — automated accessibility (Req 14.4)", () => {
  it("has no detectable axe violations on the default route", async () => {
    const { container } = renderAt("/");
    // jsdom cannot compute rendered colors (no canvas 2d context), so the
    // color-contrast rule is not machine-verifiable here — it remains a
    // manual-AT check for full WCAG 2.1 AA. All other structural rules run.
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
