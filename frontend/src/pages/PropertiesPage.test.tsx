import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import PropertiesPage from "./PropertiesPage";
import type { Property } from "../api/properties";

/**
 * Page tests for the properties list (Requirements 2.1, 2.3).
 */

function renderPage(load: () => Promise<Property[]>) {
  render(
    <MemoryRouter>
      <PropertiesPage load={load} loadPhotos={async () => []} />
    </MemoryRouter>,
  );
}

describe("PropertiesPage", () => {
  it("renders the fetched properties as a list", async () => {
    const load = vi.fn().mockResolvedValue([
      {
        id: "p1",
        user_id: "u1",
        name: "Maple Duplex",
        address_text: "1 Maple St",
        property_type: "duplex",
      },
    ] satisfies Property[]);

    renderPage(load);

    expect(
      await screen.findByRole("link", { name: "Maple Duplex" }),
    ).toBeInTheDocument();
    expect(screen.getByText("1 Maple St")).toBeInTheDocument();
  });

  it("shows an empty state prompting to add the first property", async () => {
    const load = vi.fn().mockResolvedValue([] satisfies Property[]);

    renderPage(load);

    expect(await screen.findByText(/no properties yet/i)).toBeInTheDocument();
    expect(screen.getByText(/add your first rental property/i)).toBeInTheDocument();
    // The add trigger is available (there are two: header + empty-state CTA).
    expect(
      screen.getAllByRole("button", { name: /add property/i }).length,
    ).toBeGreaterThan(0);
  });

  it("shows an error message when the load fails", async () => {
    const load = vi.fn().mockRejectedValue(new Error("boom"));

    renderPage(load);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not load your properties/i,
    );
  });
});
