import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { EmptyGuide } from "./EmptyGuide";
import { EMPTY_COPY } from "../../lib/emptyCopy";

/** Tests for EmptyGuide and emptyCopy (task 5.7, Requirements 25.4, 25.6, 27.5). */
describe("EmptyGuide", () => {
  it("renders heading, description and a primary button", async () => {
    const onClick = vi.fn();
    render(
      <MemoryRouter>
        <EmptyGuide
          title="No loans yet"
          description="Loans record balances."
          primary={{ label: "Add loan", onClick }}
        />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("heading", { name: "No loans yet" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Loans record balances.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add loan" }));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("renders link actions and a secondary link, with no landmark", async () => {
    const { container } = render(
      <MemoryRouter>
        <EmptyGuide
          title="No data for this year"
          description="Add records."
          primary={{ label: "Go to Transactions", to: "/transactions" }}
          secondary={{ label: "Import a Schedule E", to: "/imports" }}
        />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("link", { name: "Go to Transactions" }),
    ).toHaveAttribute("href", "/transactions");
    expect(
      screen.getByRole("link", { name: "Import a Schedule E" }),
    ).toHaveAttribute("href", "/imports");
    expect(
      container.querySelector("main, nav, aside, section, [role=region]"),
    ).toBeNull();
  });

  it("renders a secondary button and omits it when absent", async () => {
    const onClick = vi.fn();
    const { rerender } = render(
      <MemoryRouter>
        <EmptyGuide
          title="t"
          description="d"
          primary={{ label: "Add property", onClick: () => {} }}
          secondary={{ label: "Other", onClick }}
        />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Other" }));
    expect(onClick).toHaveBeenCalledTimes(1);
    rerender(
      <MemoryRouter>
        <EmptyGuide
          title="t"
          description="d"
          primary={{ label: "Add property", onClick: () => {} }}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("button", { name: "Other" })).toBeNull();
  });

  it("has no axe violations", async () => {
    const { container } = render(
      <MemoryRouter>
        <EmptyGuide
          title="No assets yet"
          description="Assets record items."
          primary={{ label: "Add asset", onClick: () => {} }}
          secondary={{ label: "Explore with sample data", to: "/x" }}
        />
      </MemoryRouter>,
    );
    expect((await axe(container)).violations).toHaveLength(0);
  });
});

describe("EMPTY_COPY", () => {
  const entries = Object.entries(EMPTY_COPY);

  it("has an entry for each page", () => {
    expect(Object.keys(EMPTY_COPY).sort()).toEqual(
      [
        "assets",
        "combinedReports",
        "loans",
        "properties",
        "reports",
        "repairs",
        "transactions",
      ].sort(),
    );
  });

  it.each(entries)("%s contains no tax-advice phrasing", (_k, entry) => {
    const text = `${entry.title} ${entry.description} ${entry.primaryLabel}`;
    expect(text).not.toMatch(/you should report|deductible|deduct/i);
  });

  it.each(entries)("%s names what the app records", (_k, entry) => {
    expect(entry.description).toMatch(/record/i);
    expect(entry.title).not.toBe("");
    expect(entry.primaryLabel).not.toBe("");
  });
});
