import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import type { Category, Transaction } from "../../api/transactions";
import type { OtherItem, ReportLine } from "../../api/reports";
import { TransactionList } from "../transactions/TransactionList";
import { ScheduleELineTable } from "./ScheduleELineTable";
import { OtherItemsList } from "./OtherItemsList";

/**
 * Marker-surfacing tests for Schedule E Import (task 9.2, Requirements 7.3,
 * 7.4).
 *
 * Covers the three surfaces that read the additive backend fields:
 *  - a transactions-list row with `imported: true` shows the "Imported" badge,
 *    and a non-imported row does not (Req 7.3);
 *  - a report line with `includes_imported: true` shows the indicator, and an
 *    unmarked line does not (Req 7.4);
 *  - an imported `OtherItem` shows the indicator, and an unmarked one does not
 *    (Req 7.4).
 *
 * Each surface is also checked for axe violations so the badge/indicator carries
 * an accessible label and introduces no accessibility regression.
 */

const CATEGORIES: Category[] = [
  {
    id: "cat-rent",
    kind: "income",
    label: "Rents received",
    schedule_e_line: "3",
    requires_description: false,
  },
];

function makeTransaction(overrides: Partial<Transaction> = {}): Transaction {
  return {
    id: "t1",
    property_id: "p1",
    date: "2023-12-31",
    amount: "24000.00",
    type: "income",
    category_id: "cat-rent",
    description: null,
    ...overrides,
  };
}

function renderList(transactions: readonly Transaction[]) {
  return render(
    <TransactionList
      transactions={transactions}
      categories={CATEGORIES}
      expandedId={null}
      onEdit={vi.fn()}
      onDelete={vi.fn()}
      onToggleReceipts={vi.fn()}
      renderReceipts={() => null}
    />,
  );
}

describe("TransactionList — imported badge (Req 7.3)", () => {
  it("shows the Imported badge on an imported row", () => {
    renderList([makeTransaction({ imported: true })]);

    const table = screen.getByRole("table");
    // The accessible label fully describes the badge for assistive tech.
    expect(
      within(table).getByLabelText(/imported from a schedule e import/i),
    ).toBeInTheDocument();
    expect(within(table).getByText("Imported")).toBeInTheDocument();
  });

  it("does not show the Imported badge on a user-tracked row", () => {
    renderList([makeTransaction({ imported: false })]);

    expect(screen.queryByText("Imported")).not.toBeInTheDocument();
  });

  it("treats a row with no imported field as user-tracked", () => {
    renderList([makeTransaction()]);

    expect(screen.queryByText("Imported")).not.toBeInTheDocument();
  });

  it("has no axe violations with the badge present", async () => {
    const { container } = renderList([makeTransaction({ imported: true })]);

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});

describe("ScheduleELineTable — imported indicator (Req 7.4)", () => {
  const LINES: ReportLine[] = [
    {
      line: 3,
      label: "Rents received",
      kind: "income",
      total: "24000.00",
      includes_imported: true,
    },
    {
      line: 14,
      label: "Repairs",
      kind: "expense",
      total: "1200.50",
      includes_imported: false,
    },
  ];

  it("shows the indicator only on the line that includes imported amounts", () => {
    render(
      <ScheduleELineTable caption="Schedule E lines for 2023" lines={LINES} />,
    );

    const table = screen.getByRole("table");
    const rents = within(table).getByRole("row", { name: /rents received/i });
    expect(
      within(rents).getByLabelText(/includes imported schedule e amounts/i),
    ).toBeInTheDocument();

    const repairs = within(table).getByRole("row", { name: /repairs/i });
    expect(within(repairs).queryByText("Imported")).not.toBeInTheDocument();
  });

  it("has no axe violations with the indicator present", async () => {
    const { container } = render(
      <ScheduleELineTable caption="Schedule E lines for 2023" lines={LINES} />,
    );

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});

describe("OtherItemsList — imported indicator (Req 7.4)", () => {
  const ITEMS: OtherItem[] = [
    { description: "Imported Schedule E Other", amount: "320.00", imported: true },
    { description: "Bank fees", amount: "42.50", imported: false },
  ];

  it("shows the indicator only on the imported Other item", () => {
    render(<OtherItemsList caption="Itemized Line 19 Other expenses" items={ITEMS} />);

    const table = screen.getByRole("table");
    const importedRow = within(table).getByRole("row", {
      name: /imported schedule e other/i,
    });
    expect(
      within(importedRow).getByLabelText(/imported from a schedule e import/i),
    ).toBeInTheDocument();

    const bankRow = within(table).getByRole("row", { name: /bank fees/i });
    expect(within(bankRow).queryByText("Imported")).not.toBeInTheDocument();
  });

  it("has no axe violations with the indicator present", async () => {
    const { container } = render(
      <OtherItemsList caption="Itemized Line 19 Other expenses" items={ITEMS} />,
    );

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
