import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type {
  PortfolioChecklistSummary,
  YearEndChecklistApi,
} from "../../api/yearEndChecklist";
import { YearEndDashboardCard } from "./YearEndDashboardCard";

const counts = (needs: number, done: number) => ({
  done,
  needs_attention: needs,
  not_applicable: 0,
  total: needs + done,
});

function apiWith(
  getPortfolioSummary: (year: number | null | undefined) => Promise<PortfolioChecklistSummary>,
) {
  return { getPortfolioSummary } as unknown as YearEndChecklistApi;
}

function renderCard(api: YearEndChecklistApi, taxYear: number | null) {
  return render(
    <MemoryRouter>
      <YearEndDashboardCard taxYear={taxYear} api={api} />
    </MemoryRouter>,
  );
}

describe("YearEndDashboardCard", () => {
  it("lists properties linking to their checklist for the year", async () => {
    const api = apiWith(() =>
      Promise.resolve({
        tax_year: 2024,
        properties: [
          { property_id: "p1", property_name: "Maple", counts: counts(2, 3) },
        ],
      }),
    );
    renderCard(api, 2024);
    const link = await screen.findByRole("link", { name: "Maple" });
    expect(link).toHaveAttribute("href", "/properties/p1/checklist?year=2024");
    expect(screen.getByText("2 need attention")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Year-end checklist" }),
    ).toBeInTheDocument();
  });

  it("shows a skeleton and does not fetch while the year is unknown", () => {
    const fn = vi.fn();
    renderCard(apiWith(fn), null);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(fn).not.toHaveBeenCalled();
  });

  it("renders nothing when the user owns no property", async () => {
    const api = apiWith(() => Promise.resolve({ tax_year: 2024, properties: [] }));
    const { container } = renderCard(api, 2024);
    await vi.waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    expect(container).toBeEmptyDOMElement();
  });

  it("shows an error with retry inside the card", async () => {
    const api = apiWith(() => Promise.reject(new Error("boom")));
    renderCard(api, 2024);
    expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Year-end checklist" }),
    ).toBeInTheDocument();
  });

  it("retries after an error and then shows the rows", async () => {
    const user = userEvent.setup();
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValue({
        tax_year: 2024,
        properties: [{ property_id: "p1", property_name: "Maple", counts: counts(0, 2) }],
      });
    renderCard(apiWith(fn), 2024);
    await user.click(await screen.findByRole("button", { name: /retry/i }));
    expect(await screen.findByRole("link", { name: "Maple" })).toBeInTheDocument();
    expect(screen.getByText("All clear")).toBeInTheDocument();
  });

  it("fetches once the year becomes known and reloads when it changes", async () => {
    const fn = vi.fn((year: number | null | undefined) =>
      Promise.resolve({
        tax_year: year as number,
        properties: [{ property_id: "p1", property_name: "Maple", counts: counts(1, 0) }],
      }),
    );
    const api = apiWith(fn);
    const ui = (year: number | null) => (
      <MemoryRouter>
        <YearEndDashboardCard taxYear={year} api={api} />
      </MemoryRouter>
    );
    const { rerender } = render(ui(null));
    expect(fn).not.toHaveBeenCalled();
    rerender(ui(2024));
    expect(await screen.findByRole("link", { name: "Maple" })).toHaveAttribute(
      "href",
      "/properties/p1/checklist?year=2024",
    );
    rerender(ui(2023));
    await vi.waitFor(() =>
      expect(screen.getByRole("link", { name: "Maple" })).toHaveAttribute(
        "href",
        "/properties/p1/checklist?year=2023",
      ),
    );
    expect(fn.mock.calls.map((c) => c[0])).toEqual([2024, 2023]);
  });
});
