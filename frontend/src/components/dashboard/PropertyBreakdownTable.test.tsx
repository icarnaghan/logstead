import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { PropertyBreakdownTable } from "./PropertyBreakdownTable";
import type { PropertySummary } from "../../api/dashboard";

/**
 * Component tests for {@link PropertyBreakdownTable} (task 24.3, Req 11.2).
 *
 * Verifies one row per property with the name linking to that property's
 * transactions, income/expenses/net formatted as money, a "(loss)" cue on
 * negative-net rows (Req 11.1/14.4), and an accessible table caption. The
 * component renders a react-router `Link`, so it is wrapped in a MemoryRouter.
 */

const PROPERTIES: PropertySummary[] = [
  {
    property_id: "prop-1",
    property_name: "Maple Duplex",
    total_income: "24000.00",
    total_expenses: "7175.33",
    net: "16824.67",
  },
  {
    property_id: "prop-2",
    property_name: "Oak Cottage",
    total_income: "1000.00",
    total_expenses: "1500.00",
    net: "-500.00",
  },
];

function renderTable(properties: PropertySummary[] = PROPERTIES, taxYear = 2024) {
  return render(
    <MemoryRouter>
      <PropertyBreakdownTable properties={properties} taxYear={taxYear} />
    </MemoryRouter>,
  );
}

describe("PropertyBreakdownTable — rows (Req 11.2)", () => {
  it("renders one row per property with formatted income/expenses/net", () => {
    renderTable();

    const table = screen.getByRole("table");
    const rowgroups = within(table).getAllByRole("rowgroup");
    const bodyRows = within(rowgroups[1]).getAllByRole("row");
    expect(bodyRows).toHaveLength(2);

    const maple = within(rowgroups[1]).getByRole("row", { name: /maple duplex/i });
    expect(within(maple).getByText("$24,000.00")).toBeInTheDocument();
    expect(within(maple).getByText("$7,175.33")).toBeInTheDocument();
    expect(within(maple).getByText("$16,824.67")).toBeInTheDocument();
  });

  it("links each property name to its transactions page", () => {
    renderTable();

    expect(
      screen.getByRole("link", { name: "Maple Duplex" }),
    ).toHaveAttribute("href", "/properties/prop-1/transactions");
    expect(
      screen.getByRole("link", { name: "Oak Cottage" }),
    ).toHaveAttribute("href", "/properties/prop-2/transactions");
  });
});

describe("PropertyBreakdownTable — loss cue (Req 11.1, 14.4)", () => {
  it("shows a '(loss)' cue and the negative amount on a negative-net row only", () => {
    renderTable();

    const oak = within(screen.getByRole("table")).getByRole("row", {
      name: /oak cottage/i,
    });
    expect(within(oak).getByText("-$500.00")).toBeInTheDocument();
    expect(within(oak).getByText(/\(loss\)/i)).toBeInTheDocument();

    // The profitable row carries no loss cue.
    const maple = within(screen.getByRole("table")).getByRole("row", {
      name: /maple duplex/i,
    });
    expect(within(maple).queryByText(/\(loss\)/i)).not.toBeInTheDocument();
  });
});

describe("PropertyBreakdownTable — accessibility", () => {
  it("exposes an accessible caption naming the tax year", () => {
    renderTable(PROPERTIES, 2023);

    expect(
      screen.getByRole("table", {
        name: /per-property income, expenses, and net for 2023/i,
      }),
    ).toBeInTheDocument();
  });

  it("renders no chart, canvas, or svg element", () => {
    const { container } = renderTable();

    expect(container.querySelector("canvas")).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
  });
});
