import { render, screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { ResponsiveTable } from "./ResponsiveTable";

/**
 * Unit + axe tests for the shared ResponsiveTable primitive
 * (task 3.8, Requirements 6.1, 6.2).
 *
 * One semantic table serves every viewport; Tailwind `max-sm:` classes restyle
 * rows as cards. Tests assert the single DOM and the per-cell `data-label`.
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

  it("wraps the table in an overflow-x-auto scroll wrapper", () => {
    const { container } = renderTable();
    const wrapper = screen.getByRole("table").parentElement as HTMLElement;
    expect(wrapper).toHaveClass("overflow-x-auto");
    expect(container).toContainElement(wrapper);
  });
});

describe("ResponsiveTable — single DOM for all viewports (Req 6.2)", () => {
  it("renders exactly one table and no separate card list", () => {
    const { container } = renderTable();
    expect(screen.getAllByRole("table")).toHaveLength(1);
    expect(container.querySelector("ul")).toBeNull();
    // Each value appears once, so plain single queries work.
    expect(screen.getByText("Repairs")).toBeInTheDocument();
    expect(screen.getByText("$300.00")).toBeInTheDocument();
  });

  it("labels every body cell with its column header for the stacked layout", () => {
    renderTable();
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(ROWS.length);
    for (const row of rows) {
      const labels = Array.from(row.children).map((c) => c.getAttribute("data-label"));
      expect(labels).toEqual(COLUMNS.map((c) => c.header));
    }
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
