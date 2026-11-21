import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import BusinessesPage from "./BusinessesPage";
import type { Business } from "../api/businesses";
import { PRIMARY_NAV } from "../components/navConfig";

/**
 * Page tests for the businesses list (Requirements 11.1, 11.2, 12.4).
 */

function renderPage(load: () => Promise<Business[]>) {
  return render(
    <MemoryRouter>
      <BusinessesPage load={load} />
    </MemoryRouter>,
  );
}

function makeBusiness(overrides: Partial<Business> = {}): Business {
  return {
    id: "b1",
    user_id: "u1",
    legal_name: "Maple Holdings",
    entity_type: "llc",
    tax_year_end: "12-31",
    ...overrides,
  };
}

describe("BusinessesPage", () => {
  it("renders legal_name and a human-readable entity_type for each business", async () => {
    const load = vi.fn().mockResolvedValue([
      makeBusiness({ id: "b1", legal_name: "Maple Holdings", entity_type: "llc" }),
      makeBusiness({
        id: "b2",
        legal_name: "Oak Partners",
        entity_type: "s_corporation",
      }),
    ] satisfies Business[]);

    renderPage(load);

    expect(
      await screen.findByRole("link", { name: "Maple Holdings" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Oak Partners" })).toBeInTheDocument();

    // snake_case stored values render as human labels, never the raw token.
    expect(screen.getByText("LLC")).toBeInTheDocument();
    expect(screen.getByText("S corporation")).toBeInTheDocument();
    expect(screen.queryByText("s_corporation")).not.toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("shows an empty state when the user has no businesses", async () => {
    const load = vi.fn().mockResolvedValue([] satisfies Business[]);

    renderPage(load);

    expect(await screen.findByText(/no businesses yet/i)).toBeInTheDocument();
    expect(
      screen.getByText(/add your first business entity/i),
    ).toBeInTheDocument();
  });

  it("renders the add-business trigger in the populated state", async () => {
    const load = vi.fn().mockResolvedValue([
      makeBusiness({ id: "b1", legal_name: "Maple Holdings", entity_type: "llc" }),
    ] satisfies Business[]);

    renderPage(load);

    await screen.findAllByRole("link", { name: "Maple Holdings" });

    expect(
      screen.getByRole("button", { name: "Add business" }),
    ).toBeInTheDocument();
  });

  it("renders the add-business trigger in the empty state", async () => {
    const load = vi.fn().mockResolvedValue([] satisfies Business[]);

    renderPage(load);

    await screen.findByText(/no businesses yet/i);

    // Header trigger + empty-state trigger are both present.
    expect(
      screen.getAllByRole("button", { name: "Add business" }).length,
    ).toBeGreaterThan(0);
  });

  it("shows exactly one Add business button in the empty state", async () => {
    const load = vi.fn().mockResolvedValue([] satisfies Business[]);

    renderPage(load);

    await screen.findByText(/no businesses yet/i);

    expect(screen.getAllByRole("button", { name: "Add business" })).toHaveLength(1);
  });

  it("opens the add dialog from the page trigger", async () => {
    const user = userEvent.setup();
    const load = vi.fn().mockResolvedValue([] satisfies Business[]);

    renderPage(load);

    await screen.findByText(/no businesses yet/i);
    await user.click(screen.getByRole("button", { name: "Add business" }));
    expect(
      await screen.findByRole("dialog", { name: /add a business/i }),
    ).toBeInTheDocument();
  });

  it("shows an error message when the load fails", async () => {
    const load = vi.fn().mockRejectedValue(new Error("boom"));

    renderPage(load);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not load your businesses/i,
    );
  });

  it("includes a Businesses entry in the primary navigation", () => {
    const entry = PRIMARY_NAV.find((item) => item.to === "/businesses");
    expect(entry).toBeDefined();
    expect(entry?.label).toBe("Businesses");
  });

  it("has no axe violations when businesses are loaded", async () => {
    const load = vi.fn().mockResolvedValue([
      makeBusiness({ id: "b1", legal_name: "Maple Holdings", entity_type: "llc" }),
    ] satisfies Business[]);

    const { container } = renderPage(load);

    await screen.findAllByRole("link", { name: "Maple Holdings" });

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });

  it("has no axe violations in the empty state", async () => {
    const load = vi.fn().mockResolvedValue([] satisfies Business[]);

    const { container } = renderPage(load);

    await screen.findByText(/no businesses yet/i);

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
