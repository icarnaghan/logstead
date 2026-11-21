import { render, screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { PaymentRowsTable } from "./PaymentRowsTable";
import type { PaymentRow } from "../../api/loans";

/** Tests for PaymentRowsTable on ResponsiveTable (Requirements 22.1, 22.3, 22.5). */

const rows: PaymentRow[] = [
  {
    number: 1,
    date: "2023-02-01",
    payment: "750.00",
    interest: "500.00",
    principal: "250.00",
    balance: "99750.00",
  },
  {
    number: 2,
    date: "2023-03-01",
    payment: "750.00",
    interest: "499.00",
    principal: "251.00",
    balance: "99499.00",
  },
];

describe("PaymentRowsTable", () => {
  it("renders the same columns and cent-precision values", () => {
    render(<PaymentRowsTable caption="Payments for 2023" rows={rows} />);
    const table = screen.getByRole("table", { name: "Payments for 2023" });
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(headers).toEqual([
      "Payment number",
      "Date",
      "Payment",
      "Interest",
      "Principal",
      "Balance",
    ]);
    const first = within(table).getAllByRole("row")[1];
    const cells = Array.from(first.children).map((c) => c.textContent);
    expect(cells).toEqual([
      "1",
      "2023-02-01",
      "$750.00",
      "$500.00",
      "$250.00",
      "$99,750.00",
    ]);
  });

  it("uses the payment number as a row header with scope=row", () => {
    render(<PaymentRowsTable caption="Payments" rows={rows} />);
    const table = screen.getByRole("table");
    const rowHeaders = within(table).getAllByRole("rowheader");
    expect(rowHeaders.map((h) => h.textContent)).toEqual(["1", "2"]);
    rowHeaders.forEach((h) => expect(h).toHaveAttribute("scope", "row"));
  });

  it("labels each cell with its column header for the stacked layout", () => {
    const { container } = render(
      <PaymentRowsTable caption="Payments" rows={rows} />,
    );
    expect(container.querySelector("ul")).toBeNull();
    const bodyRows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(bodyRows).toHaveLength(rows.length);
    expect(bodyRows[0].textContent).toContain("$99,750.00");
    expect(bodyRows[1].textContent).toContain("2023-03-01");
    expect(
      within(bodyRows[0]).getByText("$99,750.00").closest("[data-label]"),
    ).toBeInTheDocument();
  });

  it("right-aligns numeric columns in header and body", () => {
    render(<PaymentRowsTable caption="Payments" rows={rows} />);
    const table = screen.getByRole("table");
    for (const name of ["Payment", "Interest", "Principal", "Balance"]) {
      const th = within(table).getByRole("columnheader", { name });
      expect(th).toHaveClass("text-right");
      expect(th).toHaveClass("tabular-nums");
    }
    expect(within(table).getByRole("columnheader", { name: "Date" })).not.toHaveClass(
      "text-right",
    );
    const dataRow = within(table).getAllByRole("row")[1];
    expect(within(dataRow).getByText("$99,750.00")).toHaveClass("text-right");
  });

  it("applies a sticky header with a max-height scroll area", () => {
    const { container } = render(
      <PaymentRowsTable caption="Payments" rows={rows} />,
    );
    const th = within(screen.getByRole("table")).getByRole("columnheader", {
      name: "Date",
    });
    expect(th).toHaveClass("sticky", "top-0");
    const wrapper = container.querySelector("table")!.parentElement!;
    expect(wrapper).toHaveClass("overflow-auto", "max-h-96");
  });

  it("keeps the empty-state paragraph and renders no table", () => {
    render(<PaymentRowsTable caption="Payments" rows={[]} />);
    expect(screen.getByText("No payments in this year.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("has no duplicate ids and no axe violations", async () => {
    const { container } = render(
      <PaymentRowsTable caption="Payments" rows={rows} />,
    );
    const ids = Array.from(container.querySelectorAll("[id]")).map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
