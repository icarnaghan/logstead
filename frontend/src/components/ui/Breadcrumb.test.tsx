import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { Breadcrumb, type Crumb } from "./Breadcrumb";

/**
 * Unit + axe tests for the shared Breadcrumb primitive
 * (task 7.4, Requirements 2.2, 2.3).
 */

const ITEMS: Crumb[] = [
  { label: "Properties", to: "/properties" },
  { label: "Maple Duplex", to: "/properties/p1" },
  { label: "Transactions" },
];

function renderBreadcrumb(items: Crumb[] = ITEMS) {
  return render(
    <MemoryRouter>
      <Breadcrumb items={items} />
    </MemoryRouter>,
  );
}

describe("Breadcrumb — structure (Req 2.2)", () => {
  it("renders a nav with the accessible name 'Breadcrumb'", () => {
    renderBreadcrumb();
    expect(
      screen.getByRole("navigation", { name: "Breadcrumb" }),
    ).toBeInTheDocument();
  });

  it("renders ancestor crumbs as links with the correct hrefs", () => {
    renderBreadcrumb();
    expect(
      screen.getByRole("link", { name: "Properties" }),
    ).toHaveAttribute("href", "/properties");
    expect(
      screen.getByRole("link", { name: "Maple Duplex" }),
    ).toHaveAttribute("href", "/properties/p1");
  });
});

describe("Breadcrumb — current page (Req 2.3)", () => {
  it("renders the final crumb as text marked aria-current, not a link", () => {
    renderBreadcrumb();
    // Final crumb is not a link.
    expect(
      screen.queryByRole("link", { name: "Transactions" }),
    ).not.toBeInTheDocument();
    // Final crumb is plain text with aria-current="page".
    const current = screen.getByText("Transactions");
    expect(current).toHaveAttribute("aria-current", "page");
    expect(current.tagName).toBe("SPAN");
  });
});

describe("Breadcrumb — separators", () => {
  it("hides separators from assistive technology", () => {
    renderBreadcrumb();
    // Two ancestors -> two separators between the three crumbs.
    const nav = screen.getByRole("navigation", { name: "Breadcrumb" });
    const separators = nav.querySelectorAll('[aria-hidden="true"]');
    expect(separators).toHaveLength(2);
    // The accessible name never includes the separator glyph.
    expect(nav).toHaveAccessibleName("Breadcrumb");
    // Screen-reader text is Properties, Maple Duplex, Transactions only.
    expect(nav).toHaveTextContent(
      /Properties\s*\/\s*Maple Duplex\s*\/\s*Transactions/,
    );
  });
});

describe("Breadcrumb — accessibility", () => {
  it("has no axe violations", async () => {
    const { container } = renderBreadcrumb();
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
