import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OtherItemsList } from "./OtherItemsList";
import type { OtherItem } from "../../api/reports";

/**
 * Component tests for {@link OtherItemsList} (task 24.3, Requirement 10.5).
 *
 * Verifies the itemized Line 19 "Other" list renders a description + amount row
 * per item under an accessible caption, and shows the empty-state note when a
 * property recorded no Other expenses for the year.
 */

const ITEMS: OtherItem[] = [
  { description: "HOA dues", amount: "100.00" },
  { description: "Bank fees", amount: "42.50" },
];

describe("OtherItemsList — itemization (Req 10.5)", () => {
  it("renders a description + formatted amount row per item", () => {
    render(<OtherItemsList caption="Itemized Line 19 Other expenses" items={ITEMS} />);

    const table = screen.getByRole("table");
    const rowgroups = within(table).getAllByRole("rowgroup");
    const bodyRows = within(rowgroups[1]).getAllByRole("row");
    expect(bodyRows).toHaveLength(2);

    const hoa = within(rowgroups[1]).getByRole("row", { name: /hoa dues/i });
    expect(within(hoa).getByText("HOA dues")).toBeInTheDocument();
    expect(within(hoa).getByText("$100.00")).toBeInTheDocument();

    const bank = within(rowgroups[1]).getByRole("row", { name: /bank fees/i });
    expect(within(bank).getByText("Bank fees")).toBeInTheDocument();
    expect(within(bank).getByText("$42.50")).toBeInTheDocument();
  });

  it("exposes an accessible caption", () => {
    render(
      <OtherItemsList
        caption="Itemized Line 19 Other expenses for Maple Duplex, tax year 2024"
        items={ITEMS}
      />,
    );

    expect(
      screen.getByRole("table", {
        name: /itemized line 19 other expenses for maple duplex, tax year 2024/i,
      }),
    ).toBeInTheDocument();
  });
});

describe("OtherItemsList — empty state (Req 10.5)", () => {
  it("shows the no-Other-expenses note and no table when items is empty", () => {
    render(<OtherItemsList caption="Empty" items={[]} />);

    expect(
      screen.getByText(/no line 19 "other" expenses were recorded/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
