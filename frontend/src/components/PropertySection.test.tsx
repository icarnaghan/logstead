import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";
import { PropertySection } from "./PropertySection";
import PropertyLayout from "./PropertyLayout";
import type { Property } from "../api/properties";

/**
 * Regression tests for {@link PropertySection} on a sub-page after the Section
 * Tabs were extracted into {@link PropertySectionTabs} (task 3.2,
 * Requirements 2.3, 2.5).
 *
 * The sub-page is rendered through a real `PropertyLayout` (with an injected
 * `load`) so identity flows through the shared context exactly as in the app,
 * letting us assert the resolved property name in the breadcrumb. The page is a
 * sub-route (`/transactions`) under the `/properties/:propertyId` layout route
 * so NavLink active state resolves against the sub-route.
 */

const property: Property = {
  id: "p1",
  user_id: "u1",
  name: "Maple Duplex",
  address_text: "1 Maple St, Springfield",
  property_type: "Single Family",
};

/** Render the Transactions sub-page at `/properties/p1/transactions`. */
function renderTransactions() {
  const load = async () => property;
  return render(
    <MemoryRouter initialEntries={["/properties/p1/transactions"]}>
      <Routes>
        <Route
          path="/properties/:propertyId"
          element={<PropertyLayout load={load} />}
        >
          <Route
            path="transactions"
            element={
              <PropertySection
                title="Transactions"
                description="Record income and expenses for this property."
                propertyId="p1"
              />
            }
          />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("PropertySection sub-page — Section Tabs (Req 2.3, 2.5)", () => {
  it("renders the four section tabs in order", async () => {
    renderTransactions();
    // Let the shared context settle (property load) before asserting; the name
    // appears in both the breadcrumb and the subtitle, so scope the wait.
    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    await within(breadcrumb).findByText("Maple Duplex");

    const nav = screen.getByRole("navigation", { name: "Property sections" });
    const links = within(nav).getAllByRole("link");
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

  it("links Overview to the property index and leaves it NOT active, with Transactions active", async () => {
    renderTransactions();
    // Let the shared context settle (property load) before asserting; the name
    // appears in both the breadcrumb and the subtitle, so scope the wait.
    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    await within(breadcrumb).findByText("Maple Duplex");

    const nav = screen.getByRole("navigation", { name: "Property sections" });

    const overview = within(nav).getByRole("link", { name: "Overview" });
    expect(overview).toHaveAttribute("href", "/properties/p1");
    expect(overview).not.toHaveAttribute("aria-current");
    expect(overview.className).not.toContain("bg-accent");

    const transactions = within(nav).getByRole("link", { name: "Transactions" });
    expect(transactions).toHaveAttribute("aria-current", "page");
    expect(transactions.className).toContain("bg-accent");
  });
});

describe("PropertySection sub-page — PageHeader (Req 4.1-4.4, 4.7)", () => {
  it("renders the title as a focusable h1 with the default page-heading id", async () => {
    renderTransactions();
    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    await within(breadcrumb).findByText("Maple Duplex");

    const h1 = screen.getByRole("heading", { level: 1, name: "Transactions" });
    expect(h1).toHaveAttribute("id", "page-heading");
    expect(h1).toHaveAttribute("tabindex", "-1");
    expect(
      screen.getByText("Record income and expenses for this property."),
    ).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = renderTransactions();
    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    await within(breadcrumb).findByText("Maple Duplex");

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});

describe("PropertySection sub-page — breadcrumb (unchanged by extraction)", () => {
  it("renders the Properties > {name} > Transactions trail", async () => {
    renderTransactions();

    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    // The property name resolves from the shared context once loaded.
    expect(
      await within(breadcrumb).findByText("Maple Duplex"),
    ).toBeInTheDocument();
    expect(breadcrumb).toHaveTextContent("Properties");
    expect(breadcrumb).toHaveTextContent("Transactions");

    // "Properties" is a link to the list; the name links to the index; the
    // final crumb (Transactions) is the current, non-link page.
    expect(
      within(breadcrumb).getByRole("link", { name: "Properties" }),
    ).toHaveAttribute("href", "/properties");
    expect(
      within(breadcrumb).getByRole("link", { name: "Maple Duplex" }),
    ).toHaveAttribute("href", "/properties/p1");
    expect(
      within(breadcrumb).queryByRole("link", { name: "Transactions" }),
    ).not.toBeInTheDocument();
  });
});
