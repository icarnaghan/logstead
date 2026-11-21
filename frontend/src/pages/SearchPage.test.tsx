import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import SearchPage from "./SearchPage";
import type { SearchFn } from "../components/palette/useGlobalSearch";

const RESPONSE = {
  query: "water",
  truncated: false,
  scanned: 1,
  groups: [
    {
      kind: "transaction",
      total: 1,
      hits: [
        {
          kind: "transaction",
          id: "t1",
          property_id: "p1",
          title: "Water bill",
          subtitle: null,
          matched_field: "description",
          link: "/properties/p1/transactions?year=2024&focus=t1",
          amount: "125.00",
          date: "2024-03-07",
        },
      ],
    },
  ],
};

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

function renderPage(search: SearchFn, url = "/search") {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route
          path="/search"
          element={
            <>
              <SearchPage search={search} />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("SearchPage", () => {
  it("has one h1 and a labeled field, and searches nothing below 2 characters", async () => {
    const search = vi.fn<SearchFn>();
    renderPage(search);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    await userEvent.type(screen.getByRole("searchbox", { name: "Search" }), "w");
    expect(search).not.toHaveBeenCalled();
  });

  it("runs the search from q, shows groups, amount and date, and announces the count", async () => {
    const search = vi.fn<SearchFn>().mockResolvedValue(RESPONSE);
    renderPage(search, "/search?q=water");
    expect(
      await screen.findByRole("heading", { name: /Transactions/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/properties/p1/transactions?year=2024&focus=t1",
    );
    expect(screen.getByText(/125\.00/)).toBeInTheDocument();
    expect(search.mock.calls[0][1]).toMatchObject({ limit: 25 });
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("1 results"),
    );
  });

  it("writes the field value back to q with replace navigation", async () => {
    const search = vi.fn<SearchFn>().mockResolvedValue(RESPONSE);
    renderPage(search);
    await userEvent.type(screen.getByRole("searchbox", { name: "Search" }), "wa");
    expect(screen.getByTestId("where")).toHaveTextContent("/search?q=wa");
  });

  it("shows an error with retry, then No results", async () => {
    const search = vi
      .fn<SearchFn>()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({ ...RESPONSE, groups: [] });
    renderPage(search, "/search?q=zzz");
    expect(
      (await screen.findAllByText("Search is unavailable. Try again.")).length,
    ).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect((await screen.findAllByText("No results")).length).toBeGreaterThan(0);
  });
});
