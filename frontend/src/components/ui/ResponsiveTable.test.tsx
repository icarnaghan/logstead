import { render, screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { ResponsiveTable } from "./ResponsiveTable";

/**
 * Unit + axe tests for the shared ResponsiveTable primitive
 * (task 3.8, Requirements 6.1, 6.2).
 *
 * The design's responsive approach is CSS-driven: both the >= sm table and the
 * < sm card layout live in the DOM at once and are shown/hidden via Tailwind
 * breakpoints. Tests assert the presence of both representations and their
 * responsive classes rather than mocking matchMedia.
 */

const COLUMNS = [
  { key: "date", header: "Date" },
  { key: "category", header: "Category" },
  { key: "amount", header: "Amount", align: "right" as const },
];

const ROWS = [
  {
    id: "t1",
    cells: { date: "2024-01-05", category: "Repairs", amount: "$120.00" },
  },
  {
    id: "t2",
    cells: { date: "2024-02-10", category: "Insurance", amount: "$300.00" },
  },
];

function renderTable() {
  return render(
    <ResponsiveTable caption="Transactions for 2024" columns={COLUMNS} rows={ROWS} />,
  );
}

describe("ResponsiveTable — table representation (Req 6.1)", () => {
  it("renders a table with the accessible caption", () => {
    renderTable();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Transactions for 2024")).toBeInTheDocument();
  });

  it("renders every column header", () => {
    renderTable();
    for (const column of COLUMNS) {
      expect(
        screen.getByRole("columnheader", { name: column.header }),
      ).toBeInTheDocument();
    }
  });

  it("renders every row's cell content in the table", () => {
    renderTable();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Repairs")).toBeInTheDocument();
    expect(within(table).getByText("$120.00")).toBeInTheDocument();
    expect(within(table).getByText("Insurance")).toBeInTheDocument();
    expect(within(table).getByText("$300.00")).toBeInTheDocument();
  });

  it("wraps the table in an overflow-x-auto scroll wrapper shown at >= sm", () => {
    const { container } = renderTable();
    const table = screen.getByRole("table");
    const wrapper = table.parentElement as HTMLElement;
    expect(wrapper).toHaveClass("overflow-x-auto");
    expect(wrapper).toHaveClass("sm:block");
    expect(wrapper).toHaveClass("hidden");
    // sanity: the wrapper is inside the primitive's root.
    expect(container).toContainElement(wrapper);
  });
});

describe("ResponsiveTable — card representation (Req 6.2)", () => {
  it("also renders a card layout container hidden at >= sm", () => {
    const { container } = renderTable();
    const cardList = container.querySelector("ul.sm\\:hidden");
    expect(cardList).not.toBeNull();
    expect(cardList).toHaveClass("sm:hidden");
  });

  it("renders one card per row with header:value pairs", () => {
    const { container } = renderTable();
    const cardList = container.querySelector("ul.sm\\:hidden") as HTMLElement;
    const cards = within(cardList).getAllByRole("listitem");
    expect(cards).toHaveLength(ROWS.length);
    // Each card labels values with the column headers.
    expect(within(cardList).getAllByText("Date")).toHaveLength(ROWS.length);
    expect(within(cardList).getByText("Repairs")).toBeInTheDocument();
    expect(within(cardList).getByText("$300.00")).toBeInTheDocument();
  });
});

describe("ResponsiveTable — accessibility", () => {
  it("has no axe violations", async () => {
    const { container } = renderTable();
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
