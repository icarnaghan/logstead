import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import PropertiesPage from "./PropertiesPage";
import type { Property } from "../api/properties";
import { ToastProvider } from "../components/ui";

/**
 * Page tests for the properties list (Requirements 2.1, 2.3).
 */

function renderPage(load: () => Promise<Property[]>, url = "/") {
  render(
    <ToastProvider>
      <MemoryRouter initialEntries={[url]}>
        <PropertiesPage load={load} loadPhotos={async () => []} />
      </MemoryRouter>
    </ToastProvider>,
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
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("shows an empty state prompting to add the first property", async () => {
    const load = vi.fn().mockResolvedValue([] satisfies Property[]);

    renderPage(load);

    expect(await screen.findByText(/no properties yet/i)).toBeInTheDocument();
    expect(screen.getByText(/builds a separate schedule e report/i)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /explore with sample data/i }),
    ).toHaveAttribute("href", "/profile?focus=backup");
    // The add trigger is available (there are two: header + empty-state CTA).
    expect(
      screen.getAllByRole("button", { name: /add property/i }).length,
    ).toBeGreaterThan(0);
  });

  it("empty state shows exactly one Add property button", async () => {
    renderPage(vi.fn().mockResolvedValue([] satisfies Property[]));

    await screen.findByText(/no properties yet/i);
    expect(screen.getAllByRole("button", { name: /add property/i })).toHaveLength(1);
  });

  it("shows an error message when the load fails", async () => {
    const load = vi.fn().mockRejectedValue(new Error("boom"));

    renderPage(load);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not load your properties/i,
    );
  });
});

describe("PropertiesPage: new=1 parameter", () => {
  it("opens the add property dialog once after the load", async () => {
    renderPage(async () => [], "/?new=1");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });
});
