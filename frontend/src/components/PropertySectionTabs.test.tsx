import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { PropertySectionTabs } from "./PropertySectionTabs";

/**
 * Component tests for the shared per-property {@link PropertySectionTabs}
 * (task 3.1, Requirements 2.2, 2.4, 2.5, 5.3).
 *
 * These exercise the tabs component directly, rendered under a `MemoryRouter`
 * at a chosen route so React Router's `NavLink` resolves active state. The
 * route is wrapped in a `/properties/:propertyId/*` splat route (mirroring the
 * real property layout route) so sub-routes like `/transactions` resolve while
 * the Overview tab uses exact (`end`) matching against the index.
 */

/** Render the tabs for property `p1` at the given route. */
function renderAt(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="/properties/:propertyId/*"
          element={<PropertySectionTabs propertyId="p1" />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("PropertySectionTabs — structure (Req 2.2)", () => {
  it("renders the 'Property sections' nav landmark with five tabs in order", () => {
    renderAt("/properties/p1");

    const nav = screen.getByRole("navigation", { name: "Property sections" });
    const links = within(nav).getAllByRole("link");
    expect(links).toHaveLength(7);
    expect(links.map((link) => link.textContent)).toEqual([
      "Overview",
      "Transactions",
      "Repairs",
      "Depreciable Assets",
      "Loans",
      "Schedule E Report",
      "Checklist",
    ]);
  });

  it("targets each tab at the correct property path", () => {
    renderAt("/properties/p1");

    const nav = screen.getByRole("navigation", { name: "Property sections" });
    expect(
      within(nav).getByRole("link", { name: "Overview" }),
    ).toHaveAttribute("href", "/properties/p1");
    expect(
      within(nav).getByRole("link", { name: "Transactions" }),
    ).toHaveAttribute("href", "/properties/p1/transactions");
    expect(
      within(nav).getByRole("link", { name: "Depreciable Assets" }),
    ).toHaveAttribute("href", "/properties/p1/assets");
    expect(
      within(nav).getByRole("link", { name: "Loans" }),
    ).toHaveAttribute("href", "/properties/p1/loans");
    expect(
      within(nav).getByRole("link", { name: "Schedule E Report" }),
    ).toHaveAttribute("href", "/properties/p1/reports");
  });
});

describe("PropertySectionTabs — active state (Req 2.4, 2.5, 5.3)", () => {
  it("marks the Overview tab active on the exact index route", () => {
    renderAt("/properties/p1");

    const overview = screen.getByRole("link", { name: "Overview" });
    expect(overview).toHaveAttribute("aria-current", "page");
    expect(overview.className).toContain("bg-accent");
    expect(overview.className).toContain("text-accent-fg");
  });

  it("marks Transactions active and Overview NOT active on a sub-route (end matching)", () => {
    renderAt("/properties/p1/transactions");

    const transactions = screen.getByRole("link", { name: "Transactions" });
    expect(transactions).toHaveAttribute("aria-current", "page");
    expect(transactions.className).toContain("bg-accent");

    // The Overview tab must NOT spuriously match the sub-route thanks to `end`.
    const overview = screen.getByRole("link", { name: "Overview" });
    expect(overview).not.toHaveAttribute("aria-current");
    expect(overview.className).not.toContain("bg-accent");
  });
});

describe("PropertySectionTabs — disclosure (Req 21)", () => {
  it("renders one landmark and one list, with a button naming the current section", () => {
    renderAt("/properties/p1/loans");
    expect(
      screen.getAllByRole("navigation", { name: "Property sections" }),
    ).toHaveLength(1);
    const button = screen.getByRole("button", {
      name: "Property sections: Loans",
    });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveAttribute("aria-controls");
    expect(document.getElementById(button.getAttribute("aria-controls")!)).toBe(
      screen.getByRole("list"),
    );
  });

  it("falls back to Overview in the label on the index route", () => {
    renderAt("/properties/p1");
    expect(
      screen.getByRole("button", { name: "Property sections: Overview" }),
    ).toBeInTheDocument();
  });

  it("opens and closes on button clicks", async () => {
    const user = userEvent.setup();
    renderAt("/properties/p1");
    const button = screen.getByRole("button", { name: /Property sections/ });
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("list").className).toContain("flex-col");
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("list").className).toContain("hidden");
  });

  it("closes on Escape and returns focus to the button", async () => {
    const user = userEvent.setup();
    renderAt("/properties/p1");
    const button = screen.getByRole("button", { name: /Property sections/ });
    await user.click(button);
    screen.getByRole("link", { name: "Repairs" }).focus();
    await user.keyboard("{Escape}");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
  });

  it("closes when focus leaves the nav", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/properties/p1"]}>
        <Routes>
          <Route
            path="/properties/:propertyId/*"
            element={
              <>
                <PropertySectionTabs propertyId="p1" />
                <button type="button">Outside</button>
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
    const button = screen.getByRole("button", { name: /Property sections/ });
    await user.click(button);
    await user.click(screen.getByRole("button", { name: "Outside" }));
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("closes after a link is chosen", async () => {
    const user = userEvent.setup();
    renderAt("/properties/p1");
    const button = screen.getByRole("button", { name: /Property sections/ });
    await user.click(button);
    await user.click(screen.getByRole("link", { name: "Repairs" }));
    expect(button).toHaveAttribute("aria-expanded", "false");
  });
});
