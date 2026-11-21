import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { ResponsiveTable } from "./ResponsiveTable";
import type {
  ResponsiveTableColumn,
  ResponsiveTableRow,
} from "./ResponsiveTable";
import { TableSkeleton } from "./Skeleton";
import type { SortState } from "./tableSort";

/**
 * Tests for the ResponsiveTable upgrades (task 31.7, Requirements 20.1-20.4,
 * 20.7-20.11): sorting, sticky header, numeric alignment, row headers, detail
 * rows, card order, loading skeleton, and axe.
 */

const COLUMNS: ResponsiveTableColumn[] = [
  { key: "name", header: "Name", sortable: true, rowHeader: true },
  { key: "amount", header: "Amount", sortable: true, numeric: true, sortType: "number" },
  { key: "note", header: "Note" },
];

const ROWS: ResponsiveTableRow[] = [
  { id: "b", cells: { name: "Bravo", amount: "$20.00", note: "x" }, sortValues: { amount: 20 } },
  { id: "c", cells: { name: "Charlie", amount: "$3.00", note: "y" }, sortValues: { amount: 3 } },
  { id: "a", cells: { name: "Alpha", amount: "$100.00", note: "z" }, sortValues: { amount: 100 } },
];

function bodyNames(): string[] {
  const table = screen.getByRole("table");
  return within(table)
    .getAllByRole("rowheader")
    .map((el) => el.textContent ?? "");
}


function header(name: string): HTMLElement {
  return screen.getByRole("columnheader", { name: new RegExp(name) });
}

function clickSort(name: string) {
  fireEvent.click(within(header(name)).getByRole("button"));
}

describe("ResponsiveTable sorting (Req 20.1-20.4)", () => {
  it("renders sortable headers as th scope=col with a button and no aria-sort initially", () => {
    render(<ResponsiveTable caption="c" columns={COLUMNS} rows={ROWS} />);
    expect(header("Name")).toHaveAttribute("scope", "col");
    expect(within(header("Name")).getByRole("button")).toBeInTheDocument();
    expect(header("Name")).not.toHaveAttribute("aria-sort");
    expect(within(header("Note")).queryByRole("button")).toBeNull();
    expect(bodyNames()).toEqual(["Bravo", "Charlie", "Alpha"]);
  });

  it("cycles asc, desc, none with aria-sort on the sorted th only", () => {
    render(<ResponsiveTable caption="c" columns={COLUMNS} rows={ROWS} />);

    clickSort("Name");
    expect(header("Name")).toHaveAttribute("aria-sort", "ascending");
    expect(header("Amount")).not.toHaveAttribute("aria-sort");
    expect(bodyNames()).toEqual(["Alpha", "Bravo", "Charlie"]);

    clickSort("Name");
    expect(header("Name")).toHaveAttribute("aria-sort", "descending");
    expect(bodyNames()).toEqual(["Charlie", "Bravo", "Alpha"]);

    clickSort("Name");
    expect(header("Name")).not.toHaveAttribute("aria-sort");
    expect(bodyNames()).toEqual(["Bravo", "Charlie", "Alpha"]);
  });

  it("moves aria-sort when a different column is sorted", () => {
    render(<ResponsiveTable caption="c" columns={COLUMNS} rows={ROWS} />);
    clickSort("Name");
    clickSort("Amount");
    expect(header("Name")).not.toHaveAttribute("aria-sort");
    expect(header("Amount")).toHaveAttribute("aria-sort", "ascending");
    // numeric ordering via sortValues (3 < 20 < 100), not text order
    expect(bodyNames()).toEqual(["Charlie", "Bravo", "Alpha"]);
  });

  it("honors defaultSort in uncontrolled mode", () => {
    render(
      <ResponsiveTable
        caption="c"
        columns={COLUMNS}
        rows={ROWS}
        defaultSort={{ key: "name", direction: "desc" }}
      />,
    );
    expect(header("Name")).toHaveAttribute("aria-sort", "descending");
    expect(bodyNames()).toEqual(["Charlie", "Bravo", "Alpha"]);
  });

  it("controlled: calls onSortChange and does not change order until the prop changes", () => {
    const onSortChange = vi.fn();
    const { rerender } = render(
      <ResponsiveTable
        caption="c"
        columns={COLUMNS}
        rows={ROWS}
        sort={null}
        onSortChange={onSortChange}
      />,
    );
    clickSort("Name");
    expect(onSortChange).toHaveBeenCalledWith({ key: "name", direction: "asc" });
    expect(header("Name")).not.toHaveAttribute("aria-sort");
    expect(bodyNames()).toEqual(["Bravo", "Charlie", "Alpha"]);

    rerender(
      <ResponsiveTable
        caption="c"
        columns={COLUMNS}
        rows={ROWS}
        sort={{ key: "name", direction: "asc" }}
        onSortChange={onSortChange}
      />,
    );
    expect(header("Name")).toHaveAttribute("aria-sort", "ascending");
    expect(bodyNames()).toEqual(["Alpha", "Bravo", "Charlie"]);
  });

  it("controlled by a parent that stores the state", () => {
    function Host() {
      const [sort, setSort] = useState<SortState>(null);
      return (
        <ResponsiveTable
          caption="c"
          columns={COLUMNS}
          rows={ROWS}
          sort={sort}
          onSortChange={setSort}
        />
      );
    }
    render(<Host />);
    clickSort("Name");
    expect(bodyNames()).toEqual(["Alpha", "Bravo", "Charlie"]);
  });

  it("uncontrolled: onSortChange is also notified", () => {
    const onSortChange = vi.fn();
    render(
      <ResponsiveTable
        caption="c"
        columns={COLUMNS}
        rows={ROWS}
        onSortChange={onSortChange}
      />,
    );
    clickSort("Amount");
    expect(onSortChange).toHaveBeenCalledWith({ key: "amount", direction: "asc" });
    expect(header("Amount")).toHaveAttribute("aria-sort", "ascending");
  });

  it("sorts date columns chronologically", () => {
    const dateCols: ResponsiveTableColumn[] = [
      { key: "d", header: "Date", sortable: true, sortType: "date", rowHeader: true },
    ];
    const dateRows: ResponsiveTableRow[] = [
      { id: "1", cells: { d: "2024-03-01" } },
      { id: "2", cells: { d: "2023-12-31" } },
      { id: "3", cells: { d: "2024-01-15" } },
    ];
    render(<ResponsiveTable caption="c" columns={dateCols} rows={dateRows} />);
    clickSort("Date");
    expect(bodyNames()).toEqual(["2023-12-31", "2024-01-15", "2024-03-01"]);
  });

  it("body order follows the sort order (the stacked layout reuses it)", () => {
    render(<ResponsiveTable caption="c" columns={COLUMNS} rows={ROWS} />);
    expect(bodyNames()).toEqual(["Bravo", "Charlie", "Alpha"]);
    clickSort("Name");
    expect(bodyNames()).toEqual(["Alpha", "Bravo", "Charlie"]);
    clickSort("Name");
    expect(bodyNames()).toEqual(["Charlie", "Bravo", "Alpha"]);
  });

  it("sort icons are aria-hidden and sort buttons keep the mobile touch target", () => {
    render(<ResponsiveTable caption="c" columns={COLUMNS} rows={ROWS} />);
    const button = within(header("Name")).getByRole("button");
    expect(button).toHaveClass("max-md:min-h-11");
    expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});

describe("ResponsiveTable layout contracts (Req 20.7-20.10)", () => {
  it("applies sticky header classes and the default max height", () => {
    render(<ResponsiveTable caption="c" columns={COLUMNS} rows={ROWS} stickyHeader />);
    const th = header("Name");
    for (const cls of ["sticky", "top-0", "z-10", "bg-surface"]) {
      expect(th).toHaveClass(cls);
    }
    const wrapper = screen.getByRole("table").parentElement as HTMLElement;
    expect(wrapper).toHaveClass("overflow-auto", "max-h-[70dvh]");
  });

  it("accepts a custom maxHeightClass", () => {
    render(
      <ResponsiveTable
        caption="c"
        columns={COLUMNS}
        rows={ROWS}
        stickyHeader
        maxHeightClass="max-h-96"
      />,
    );
    const wrapper = screen.getByRole("table").parentElement as HTMLElement;
    expect(wrapper).toHaveClass("max-h-96");
    expect(wrapper).not.toHaveClass("max-h-[70dvh]");
  });

  it("does not apply sticky classes by default", () => {
    render(<ResponsiveTable caption="c" columns={COLUMNS} rows={ROWS} />);
    expect(header("Name")).not.toHaveClass("sticky");
    const wrapper = screen.getByRole("table").parentElement as HTMLElement;
    expect(wrapper).toHaveClass("overflow-x-auto");
    expect(wrapper).not.toHaveClass("max-h-[70dvh]");
  });

  it("rows have hover and focus-within highlight classes", () => {
    render(<ResponsiveTable caption="c" columns={COLUMNS} rows={ROWS} />);
    const row = screen.getByRole("table").querySelector("tbody tr") as HTMLElement;
    expect(row).toHaveClass("hover:bg-surface-muted", "focus-within:bg-surface-muted");
  });

  it("right-aligns numeric columns with tabular-nums in header and body", () => {
    render(<ResponsiveTable caption="c" columns={COLUMNS} rows={ROWS} />);
    expect(header("Amount")).toHaveClass("text-right", "tabular-nums");
    const cell = within(screen.getByRole("table")).getByText("$20.00");
    expect(cell).toHaveClass("text-right", "tabular-nums");
    expect(header("Name")).not.toHaveClass("text-right");
  });

  it("renders rowHeader cells as th scope=row and others as td", () => {
    render(<ResponsiveTable caption="c" columns={COLUMNS} rows={ROWS} />);
    const rowHeaders = screen.getAllByRole("rowheader");
    expect(rowHeaders).toHaveLength(ROWS.length);
    for (const th of rowHeaders) {
      expect(th.tagName).toBe("TH");
      expect(th).toHaveAttribute("scope", "row");
    }
    expect(within(screen.getByRole("table")).getByText("x").tagName).toBe("TD");
  });
});

describe("ResponsiveTable detail rows (Req 20.11)", () => {
  const detailRows: ResponsiveTableRow[] = [
    {
      id: "r1",
      cells: { name: "One", amount: "1", note: "n1" },
      detail: <p>Detail one</p>,
      detailId: "detail-r1",
      detailOpen: true,
    },
    {
      id: "r2",
      cells: { name: "Two", amount: "2", note: "n2" },
      detail: <p>Detail two</p>,
      detailId: "detail-r2",
      detailOpen: false,
    },
    { id: "r3", cells: { name: "Three", amount: "3", note: "n3" } },
  ];

  it("renders a detail row after its row with colSpan, id, and hidden when closed", () => {
    const { container } = render(
      <ResponsiveTable caption="c" columns={COLUMNS} rows={detailRows} />,
    );
    const open = container.querySelector("#detail-r1") as HTMLElement;
    const closed = container.querySelector("#detail-r2") as HTMLElement;
    expect(open).not.toBeNull();
    expect(open).not.toHaveAttribute("hidden");
    expect(closed).toHaveAttribute("hidden");
    expect(open.previousElementSibling).toHaveTextContent("One");
    expect(closed.previousElementSibling).toHaveTextContent("Two");
    expect(open.querySelector("td")).toHaveAttribute(
      "colspan",
      String(COLUMNS.length),
    );
    // Row without detail renders no extra row: 3 rows + 2 detail rows.
    expect(container.querySelectorAll("tbody tr")).toHaveLength(5);
  });

  it("renders each detail once and reveals only the open one on narrow screens", () => {
    render(<ResponsiveTable caption="c" columns={COLUMNS} rows={detailRows} />);
    const openRow = screen.getByText("Detail one").closest("tr") as HTMLElement;
    const closedRow = screen.getByText("Detail two").closest("tr") as HTMLElement;
    expect(openRow).toHaveClass("max-sm:block");
    expect(closedRow).not.toHaveClass("max-sm:block");
    expect(closedRow).toHaveAttribute("hidden");
  });
});

describe("ResponsiveTable loading and no-sort rendering", () => {
  it("renders the TableSkeleton unchanged while loading", () => {
    const loading = render(
      <ResponsiveTable caption="c" columns={COLUMNS} rows={ROWS} loading />,
    );
    const skeleton = render(<TableSkeleton columns={COLUMNS.length} />);
    expect(loading.container.innerHTML).toBe(skeleton.container.innerHTML);
    expect(screen.queryByRole("table", { name: "c" })).toBeNull();
  });

  it("renders plain headers and rows in source order with no sortable columns", () => {
    const plain: ResponsiveTableColumn[] = [
      { key: "name", header: "Name" },
      { key: "note", header: "Note" },
    ];
    render(<ResponsiveTable caption="c" columns={plain} rows={ROWS} />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    for (const th of screen.getAllByRole("columnheader")) {
      expect(th).not.toHaveAttribute("aria-sort");
    }
    expect(screen.getAllByRole("rowgroup")[1].querySelectorAll("tr")).toHaveLength(
      ROWS.length,
    );
    expect(screen.queryAllByRole("rowheader")).toHaveLength(0);
  });
});

describe("ResponsiveTable upgrades accessibility", () => {
  it("has no axe violations with sort, sticky header, row headers, and details", async () => {
    const rows: ResponsiveTableRow[] = ROWS.map((r, i) => ({
      ...r,
      detail: <p>Detail {i}</p>,
      detailId: `d-${i}`,
      detailOpen: i === 0,
    }));
    const { container } = render(
      <ResponsiveTable
        caption="Accessible table"
        columns={COLUMNS}
        rows={rows}
        stickyHeader
        defaultSort={{ key: "name", direction: "asc" }}
      />,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
