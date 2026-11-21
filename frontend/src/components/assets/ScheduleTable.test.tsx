import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { ScheduleTable } from "./ScheduleTable";
import type { ScheduleRow } from "../../api/assets";

/**
 * Component tests for the depreciation schedule display (task 23.2,
 * Requirement 9.4).
 *
 * The schedule is deliberately a numeric data table — never a chart. These
 * tests assert the tax_year / amount / remaining_basis columns render in
 * order, money amounts render through formatMoneyWholeDollars (Req 11.2 — the
 * depreciation schedule is a tax-oriented surface that mirrors a filed return)
 * with no float drift, the empty state message appears, the table exposes an
 * accessible caption, and there is no canvas/svg chart element.
 */

function row(overrides: Partial<ScheduleRow> = {}): ScheduleRow {
  return {
    tax_year: 2023,
    amount: "5833.33",
    remaining_basis: "269166.67",
    method: "straight-line",
    convention: "mid-month",
    ...overrides,
  };
}

// Scope queries to the single rendered table.
const inTable = () => within(screen.getByRole("table"));

const rows: ScheduleRow[] = [
  row({ tax_year: 2023, amount: "5833.33", remaining_basis: "269166.67" }),
  row({ tax_year: 2024, amount: "10000.00", remaining_basis: "259166.67" }),
  row({ tax_year: 2025, amount: "10000.00", remaining_basis: "249166.67" }),
];

describe("ScheduleTable — numeric table (Req 9.4)", () => {
  it("renders a table with tax_year / amount / remaining_basis rows in order", () => {
    render(<ScheduleTable caption="Depreciation for Rental building" rows={rows} />);

    const table = screen.getByRole("table");
    const bodyRows = within(table).getAllByRole("row");
    // Header row + one row per schedule entry.
    expect(bodyRows).toHaveLength(rows.length + 1);

    const dataRows = bodyRows.slice(1);
    expect(within(dataRows[0]).getByText("2023")).toBeInTheDocument();
    expect(within(dataRows[1]).getByText("2024")).toBeInTheDocument();
    expect(within(dataRows[2]).getByText("2025")).toBeInTheDocument();
  });

  it("formats money amounts through formatMoneyWholeDollars (no float coercion)", () => {
    render(<ScheduleTable caption="Depreciation schedule" rows={rows} />);

    const table = screen.getByRole("table");
    // The depreciation schedule is a tax-oriented surface, so amounts render
    // rounded to the nearest whole dollar (Req 11.2): 5833.33 -> $5,833,
    // 269166.67 -> $269,167, 249166.67 -> $249,167. Rounding is integer-cents
    // only, so there is no float drift.
    expect(within(table).getByText("$5,833")).toBeInTheDocument();
    expect(within(table).getByText("$269,167")).toBeInTheDocument();
    expect(within(table).getByText("$249,167")).toBeInTheDocument();
    // Whole-dollar amounts render with no cents shown.
    expect(within(table).getAllByText("$10,000").length).toBeGreaterThan(0);
  });

  it("exposes an accessible caption", () => {
    render(
      <ScheduleTable caption="Depreciation for Rental building" rows={rows} />,
    );

    const table = screen.getByRole("table", {
      name: /depreciation for rental building/i,
    });
    expect(table).toBeInTheDocument();
  });

  it("shows a no-schedule message when the schedule is empty", () => {
    render(<ScheduleTable caption="Empty schedule" rows={[]} />);

    expect(screen.getByText(/no depreciation schedule/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders no chart element (no canvas/svg)", () => {
    const { container } = render(
      <ScheduleTable caption="Depreciation schedule" rows={rows} />,
    );

    expect(container.querySelector("canvas")).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
  });

  it("has no detectable accessibility violations", async () => {
    const { container } = render(
      <ScheduleTable caption="Depreciation for Rental building" rows={rows} />,
    );

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});

// Feature: depreciation-override-and-whole-dollar-display, Req 6.1, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3
//
// Override affordances on the editable schedule table. When `editable`, each
// row exposes a per-year override input (labelled "Depreciation override for
// <year>") and a Clear control (Req 6.1). A year present in `overrides` shows
// the textual "Filed value" marker and the pinned-to-filed-return note
// (Req 7.1, 7.2). With no overrides and not editable, no marker renders and the
// table looks as it does today (Req 7.3). `overrideErrors[<year>]` surfaces
// inline as a role="alert" next to the offending year's control (Req 6.4).
// Submitting a value (blur or Enter) calls `onOverrideChange(year, "<money
// string>")`; clicking Clear calls `onOverrideChange(year, null)` (Req 6.3).
// Amounts are handled as strings throughout (Req 6.5).
describe("ScheduleTable — override affordances (Req 6, 7)", () => {
  it("renders a per-year override input and a Clear control for each row when editable (Req 6.1)", () => {
    render(
      <ScheduleTable
        caption="Depreciation schedule"
        rows={rows}
        editable
        onOverrideChange={vi.fn()}
      />,
    );

    // Each schedule year gets an accessible, labelled override input.
    for (const r of rows) {
      expect(
        inTable().getByLabelText(`Depreciation override for ${r.tax_year}`),
      ).toBeInTheDocument();
      expect(
        inTable().getByRole("button", {
          name: `Clear depreciation override for ${r.tax_year}`,
        }),
      ).toBeInTheDocument();
    }
  });

  it("does not render override inputs when not editable (Req 7.3)", () => {
    render(<ScheduleTable caption="Depreciation schedule" rows={rows} />);

    expect(
      inTable().queryByLabelText(/depreciation override for/i),
    ).not.toBeInTheDocument();
    expect(
      inTable().queryByRole("button", { name: /clear depreciation override/i }),
    ).not.toBeInTheDocument();
  });

  it("shows the textual 'Filed value' marker and pinned note for an overridden year (Req 7.1, 7.2)", () => {
    render(
      <ScheduleTable
        caption="Depreciation schedule"
        rows={rows}
        overrides={{ "2023": "1952.00" }}
      />,
    );

    const table = screen.getByRole("table");
    // Textual marker — never color alone (Req 7.1).
    expect(within(table).getByText("Filed value")).toBeInTheDocument();
    // One-line note explaining the year is pinned to a filed return (Req 7.2).
    expect(
      within(table).getByText(
        /pinned to reproduce the amount from a filed return/i,
      ),
    ).toBeInTheDocument();
  });

  it("renders no marker and presents the schedule as today when there are no overrides (Req 7.3)", () => {
    render(<ScheduleTable caption="Depreciation schedule" rows={rows} />);

    const table = screen.getByRole("table");
    expect(within(table).queryByText("Filed value")).not.toBeInTheDocument();
    expect(
      within(table).queryByText(/pinned to reproduce/i),
    ).not.toBeInTheDocument();
    // The computed amounts still render as whole dollars, exactly as the
    // read-only table does elsewhere.
    expect(within(table).getByText("$5,833")).toBeInTheDocument();
  });

  it("renders overrideErrors inline as an alert next to the offending year's control (Req 6.4)", () => {
    render(
      <ScheduleTable
        caption="Depreciation schedule"
        rows={rows}
        editable
        onOverrideChange={vi.fn()}
        overrideErrors={{ "2023": "Override exceeds remaining basis." }}
      />,
    );

    const alert = inTable().getByRole("alert");
    expect(alert).toHaveTextContent("Override exceeds remaining basis.");

    // The alert is wired to the 2023 input via aria-describedby, so it reads as
    // belonging to that year's control.
    const input = inTable().getByLabelText("Depreciation override for 2023");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", alert.id);

    // Years without an error carry no alert / invalid state.
    expect(
      inTable().getByLabelText("Depreciation override for 2024"),
    ).not.toHaveAttribute("aria-invalid");
  });

  it("calls onOverrideChange with the normalized money string when a value is submitted via blur (Req 6.3, 6.5)", async () => {
    const user = userEvent.setup();
    const onOverrideChange = vi.fn();
    render(
      <ScheduleTable
        caption="Depreciation schedule"
        rows={rows}
        editable
        onOverrideChange={onOverrideChange}
      />,
    );

    const input = inTable().getByLabelText("Depreciation override for 2023");
    await user.type(input, "1952");
    // Blur the field to submit.
    await user.tab();

    // Amount is handled as a two-decimal money string, never a number (Req 6.5).
    expect(onOverrideChange).toHaveBeenCalledWith(2023, "1952.00");
    const [, submitted] = onOverrideChange.mock.calls[0];
    expect(typeof submitted).toBe("string");
  });

  it("calls onOverrideChange with the normalized money string when a value is submitted via Enter (Req 6.3, 6.5)", async () => {
    const user = userEvent.setup();
    const onOverrideChange = vi.fn();
    render(
      <ScheduleTable
        caption="Depreciation schedule"
        rows={rows}
        editable
        onOverrideChange={onOverrideChange}
      />,
    );

    const input = inTable().getByLabelText("Depreciation override for 2024");
    await user.type(input, "1234.5{Enter}");

    expect(onOverrideChange).toHaveBeenCalledWith(2024, "1234.50");
  });

  it("calls onOverrideChange with null when Clear is clicked for an overridden year (Req 6.3)", async () => {
    const user = userEvent.setup();
    const onOverrideChange = vi.fn();
    render(
      <ScheduleTable
        caption="Depreciation schedule"
        rows={rows}
        editable
        overrides={{ "2023": "1952.00" }}
        onOverrideChange={onOverrideChange}
      />,
    );

    await user.click(
      inTable().getByRole("button", {
        name: "Clear depreciation override for 2023",
      }),
    );

    expect(onOverrideChange).toHaveBeenCalledWith(2023, null);
  });
});

describe("ScheduleTable — ResponsiveTable migration (Req 22.2, 22.3, 22.4)", () => {
  it("renders row headers with scope=row and right-aligned numeric columns", () => {
    render(<ScheduleTable caption="Depreciation schedule" rows={rows} />);
    const table = inTable();
    const headers = table.getAllByRole("rowheader");
    expect(headers.map((h) => h.textContent)).toEqual(["2023", "2024", "2025"]);
    headers.forEach((h) => expect(h).toHaveAttribute("scope", "row"));
    for (const name of ["Depreciation amount", "Remaining basis"]) {
      expect(table.getByRole("columnheader", { name })).toHaveClass(
        "text-right",
        "tabular-nums",
      );
    }
    expect(table.getByText("$5,833")).toHaveClass("text-right");
  });

  it("labels each cell with its column header for the stacked layout", () => {
    const { container } = render(
      <ScheduleTable caption="Depreciation schedule" rows={rows} />,
    );
    expect(container.querySelector("ul")).toBeNull();
    const firstRow = inTable().getAllByRole("row")[1];
    expect(firstRow.textContent).toContain("$5,833");
    expect(firstRow.textContent).toContain("$269,167");
    expect(
      within(firstRow).getByText("$5,833").closest("[data-label]"),
    ).toHaveAttribute("data-label", "Depreciation amount");
  });

  it("has no duplicate ids when editable, with errors shown", () => {
    const { container } = render(
      <ScheduleTable
        caption="Depreciation schedule"
        rows={rows}
        editable
        onOverrideChange={vi.fn()}
        overrideErrors={{ "2023": "Too high", "2024": "Too low" }}
      />,
    );
    const ids = Array.from(container.querySelectorAll("[id]")).map((e) => e.id);
    expect(ids.length).toBeGreaterThan(0);
    expect(new Set(ids).size).toBe(ids.length);
    // Each rendered input points at its own error element.
    container.querySelectorAll("input[aria-describedby]").forEach((input) => {
      const target = container.querySelector(
        `#${input.getAttribute("aria-describedby")}`,
      );
      expect(target).not.toBeNull();
    });
  });

  it("has no axe violations when editable", async () => {
    const { container } = render(
      <ScheduleTable
        caption="Depreciation schedule"
        rows={rows}
        editable
        overrides={{ "2023": "1952.00" }}
        onOverrideChange={vi.fn()}
      />,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});

