import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import PropertyLayout, { usePropertyContext } from "./PropertyLayout";
import type { Property } from "../api/properties";

/**
 * Tests for the `PropertyLayout` layout route. It fetches a property once and
 * provides `{ propertyId, status, property }` to child routes via
 * `<Outlet context>`. Children present the property by NAME and must never see
 * the raw property id leaked as user-facing content (Requirements 2.1, 3.1).
 */

const RAW_ID = "11111111-2222-3333-4444-555555555555";

const sampleProperty: Property = {
  id: RAW_ID,
  user_id: "u1",
  name: "Maple Duplex",
  address_text: "1 Maple St, Springfield",
  property_type: "Single Family",
};

/** A child route that renders the shared context so tests can assert on it. */
function ContextProbe() {
  const { status, property } = usePropertyContext();
  return (
    <div>
      <p data-testid="status">{status}</p>
      <p data-testid="name">{property?.name ?? "Property"}</p>
    </div>
  );
}

/**
 * Render the layout with a child probe route. `load` is an injectable loader
 * returning a controllable promise so each test drives loading/loaded/error.
 */
function renderLayout(load: (id: string) => Promise<Property>) {
  return render(
    <MemoryRouter initialEntries={[`/properties/${RAW_ID}`]}>
      <Routes>
        <Route
          path="/properties/:propertyId"
          element={<PropertyLayout load={load} />}
        >
          <Route index element={<ContextProbe />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("PropertyLayout", () => {
  it("exposes a loading status before the loader resolves, without leaking the raw id", () => {
    // A promise that never resolves during this synchronous assertion window.
    renderLayout(() => new Promise<Property>(() => {}));

    expect(screen.getByTestId("status")).toHaveTextContent("loading");
    // The raw id must not appear as user-facing content while loading.
    expect(screen.queryByText(RAW_ID)).not.toBeInTheDocument();
    expect(screen.getByTestId("name")).toHaveTextContent("Property");
  });

  it("provides the loaded property name to children and never the raw id", async () => {
    renderLayout(async () => sampleProperty);

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("loaded"),
    );
    expect(screen.getByTestId("name")).toHaveTextContent("Maple Duplex");
    // The property is presented by name; the raw UUID is never shown.
    expect(screen.queryByText(RAW_ID)).not.toBeInTheDocument();
  });

  it("surfaces an error status with a neutral fallback and no raw id on load failure", async () => {
    renderLayout(async () => {
      throw new Error("boom");
    });

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("error"),
    );
    // Neutral fallback, and the raw id is not leaked.
    expect(screen.getByTestId("name")).toHaveTextContent("Property");
    expect(screen.queryByText(RAW_ID)).not.toBeInTheDocument();
  });
});
