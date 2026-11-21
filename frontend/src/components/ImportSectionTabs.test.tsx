import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";
import { ImportSectionTabs } from "./ImportSectionTabs";
import { sectionTabClassName } from "./sectionTabStyles";

/**
 * Component tests for {@link ImportSectionTabs}
 * (task 2.3, Requirements 9.2, 10.1-10.4, 10.6).
 *
 * Rendered under a `MemoryRouter` at a chosen route inside an `/imports/*`
 * splat route, mirroring the real imports layout route.
 */

function LocationProbe() {
  return <div data-testid="pathname">{useLocation().pathname}</div>;
}

function renderAt(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="/imports/*"
          element={
            <>
              <ImportSectionTabs />
              <LocationProbe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

const MANUAL = "/imports/schedule-e";
const PDF = "/imports/schedule-e/extract";

describe("ImportSectionTabs — structure (Req 10.1, 10.3)", () => {
  it("renders the 'Import methods' nav landmark with two links in order", () => {
    renderAt(MANUAL);

    const nav = screen.getByRole("navigation", { name: "Import methods" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual([
      "Enter manually",
      "Upload PDF",
    ]);
    expect(links[0]).toHaveAttribute("href", MANUAL);
    expect(links[1]).toHaveAttribute("href", PDF);
  });
});

describe("ImportSectionTabs — active state (Req 9.2, 10.4, 10.6)", () => {
  it("marks only Enter manually active on the manual route", () => {
    renderAt(MANUAL);

    const manual = screen.getByRole("link", { name: "Enter manually" });
    const pdf = screen.getByRole("link", { name: "Upload PDF" });
    expect(manual).toHaveAttribute("aria-current", "page");
    expect(pdf).not.toHaveAttribute("aria-current");
    expect(manual.className).toBe(sectionTabClassName(true));
    expect(pdf.className).toBe(sectionTabClassName(false));
  });

  it("marks only Upload PDF active on the PDF route (Manual not marked)", () => {
    renderAt(PDF);

    const manual = screen.getByRole("link", { name: "Enter manually" });
    const pdf = screen.getByRole("link", { name: "Upload PDF" });
    expect(pdf).toHaveAttribute("aria-current", "page");
    expect(manual).not.toHaveAttribute("aria-current");
    expect(pdf.className).toBe(sectionTabClassName(true));
    expect(manual.className).toBe(sectionTabClassName(false));
  });
});

describe("ImportSectionTabs — keyboard (Req 10.4)", () => {
  it("Tab focuses the links in order and Enter navigates", async () => {
    const user = userEvent.setup();
    renderAt(MANUAL);

    await user.tab();
    expect(screen.getByRole("link", { name: "Enter manually" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("link", { name: "Upload PDF" })).toHaveFocus();

    await user.keyboard("{Enter}");
    expect(screen.getByTestId("pathname")).toHaveTextContent(PDF);
    expect(screen.getByRole("link", { name: "Upload PDF" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      screen.getByRole("link", { name: "Enter manually" }),
    ).not.toHaveAttribute("aria-current");
  });
});

describe("ImportSectionTabs — accessibility", () => {
  it("has no axe violations", async () => {
    const { container } = renderAt(PDF);
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
