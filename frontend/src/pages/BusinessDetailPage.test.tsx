import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { axe } from "vitest-axe";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BusinessDetailPage from "./BusinessDetailPage";
import {
  setBusinessesClient,
  resetBusinessesClient,
  type BusinessWithLinks,
} from "../api/businesses";
import { ApiClient } from "../lib/apiClient";

function business(overrides: Partial<BusinessWithLinks> = {}): BusinessWithLinks {
  return {
    id: "b1",
    user_id: "user-1",
    legal_name: "Acme Holdings LLC",
    entity_type: "llc",
    ein: "12-3456789",
    formation_state: "CA",
    formation_date: "2020-01-15",
    tax_year_end: "12-31",
    business_address: "1 Market St, San Francisco, CA",
    note: "Primary holding entity.",
    linked_properties: [
      { id: "p1", name: "123 Oak Street" },
      { id: "p2", name: "456 Pine Avenue" },
    ],
    ...overrides,
  };
}

/**
 * Install a fake businesses API client so the embedded BusinessDocuments
 * component's real `listDocuments` call resolves to an empty list rather than
 * hitting the network. The page's own `getBusiness` is supplied via the `load`
 * seam, so only the documents GET flows through this client.
 */
function installEmptyDocumentsClient() {
  const fetchImpl: typeof fetch = async () =>
    new Response(JSON.stringify([]), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  setBusinessesClient(new ApiClient({ baseUrl: "http://test", fetchImpl }));
}

function renderPage(
  load: (id: string) => Promise<BusinessWithLinks>,
  businessId = "b1",
) {
  return render(
    <MemoryRouter initialEntries={[`/businesses/${businessId}`]}>
      <Routes>
        <Route
          path="/businesses/:businessId"
          element={<BusinessDetailPage load={load} />}
        />
        <Route path="/businesses" element={<div>Businesses list</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  installEmptyDocumentsClient();
});

afterEach(() => {
  resetBusinessesClient();
  vi.restoreAllMocks();
});

describe("BusinessDetailPage — business fields (Req 3.2, 11.3)", () => {
  it("shows the business legal_name as the heading and its detail fields", async () => {
    const load = vi.fn(async () => business());
    renderPage(load);

    const heading = await screen.findByRole("heading", {
      name: "Acme Holdings LLC",
      level: 1,
    });
    expect(heading).toBeInTheDocument();

    // A human label for the entity_type, not the raw token.
    expect(screen.getByText("LLC")).toBeInTheDocument();
    expect(screen.queryByText("llc")).not.toBeInTheDocument();
    expect(screen.getByText("12-3456789")).toBeInTheDocument();
  });
});

describe("BusinessDetailPage — linked properties (Req 10.2, 10.3)", () => {
  it("lists linked property NAMES, never raw ids", async () => {
    const load = vi.fn(async () => business());
    renderPage(load);

    await screen.findByRole("heading", { name: "Acme Holdings LLC" });

    expect(screen.getByText("123 Oak Street")).toBeInTheDocument();
    expect(screen.getByText("456 Pine Avenue")).toBeInTheDocument();
    // Raw property ids must not surface where a name exists.
    expect(screen.queryByText("p1")).not.toBeInTheDocument();
    expect(screen.queryByText("p2")).not.toBeInTheDocument();
  });

  it("shows an empty state when no properties are linked", async () => {
    const load = vi.fn(async () => business({ linked_properties: [] }));
    renderPage(load);

    await screen.findByRole("heading", { name: "Acme Holdings LLC" });
    expect(
      screen.getByText(/no properties are linked to this business yet/i),
    ).toBeInTheDocument();
  });
});

describe("BusinessDetailPage — states", () => {
  it("renders an error state when loading fails", async () => {
    const load = vi.fn(async () => {
      throw new Error("boom");
    });
    renderPage(load);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not load this business/i);
  });
});

describe("BusinessDetailPage — accessibility (Req 12.4)", () => {
  it("has no detectable axe violations", async () => {
    const load = vi.fn(async () => business());
    const { container } = renderPage(load);

    await screen.findByRole("heading", { name: "Acme Holdings LLC" });
    // Wait for the embedded documents section to settle out of its loading
    // state so the accessibility snapshot is of the final tree.
    await waitFor(() => {
      expect(
        within(container).queryByText(/loading documents…/i),
      ).not.toBeInTheDocument();
    });

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
