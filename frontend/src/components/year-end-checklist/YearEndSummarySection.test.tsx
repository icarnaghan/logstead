import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { PropertyChecklistSummary } from "../../api/yearEndChecklist";
import { YearEndSummarySection } from "./YearEndSummarySection";

const counts = (needs: number, done: number, na = 0) => ({
  done,
  needs_attention: needs,
  not_applicable: na,
  total: needs + done + na,
});

function renderSection(loadSummary: ReturnType<typeof vi.fn>) {
  return render(
    <MemoryRouter>
      <YearEndSummarySection propertyId="p1" loadSummary={loadSummary} />
    </MemoryRouter>,
  );
}

describe("YearEndSummarySection", () => {
  it("shows a skeleton, then one row per year with links", async () => {
    let resolve: (v: PropertyChecklistSummary) => void = () => {};
    const load = vi.fn(
      () => new Promise<PropertyChecklistSummary>((r) => (resolve = r)),
    );
    renderSection(load);
    expect(screen.getByLabelText("Loading year-end checklist")).toBeInTheDocument();
    resolve({
      property_id: "p1",
      years: [
        { tax_year: 2024, counts: counts(2, 5, 1) },
        { tax_year: 2023, counts: counts(0, 6) },
      ],
    });
    expect(await screen.findByText("2 need attention")).toBeInTheDocument();
    expect(screen.getByText("All clear")).toBeInTheDocument();
    expect(screen.getByText("2 need attention, 5 done, 1 not applicable")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open 2024 checklist" })).toHaveAttribute(
      "href",
      "/properties/p1/checklist?year=2024",
    );
    expect(screen.getByRole("link", { name: "Open 2023 checklist" })).toHaveAttribute(
      "href",
      "/properties/p1/checklist?year=2023",
    );
  });

  it("shows an error with retry that reloads", async () => {
    const user = userEvent.setup();
    const load = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValue({ property_id: "p1", years: [{ tax_year: 2024, counts: counts(1, 0) }] });
    renderSection(load);
    await user.click(await screen.findByRole("button", { name: /retry/i }));
    expect(await screen.findByText("1 needs attention", { selector: "span" })).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("shows an empty state linking to Transactions", async () => {
    renderSection(vi.fn().mockResolvedValue({ property_id: "p1", years: [] }));
    expect(await screen.findByText("No years to check yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to Transactions" })).toHaveAttribute(
      "href",
      "/properties/p1/transactions",
    );
  });
});
