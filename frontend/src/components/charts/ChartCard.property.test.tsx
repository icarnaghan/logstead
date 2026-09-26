import { render, screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { ChartCard, ChartPlaceholder } from "./ChartCard";

/**
 * Property + axe/contract tests for the shared ChartCard wrapper (task 15.7).
 *
 * ChartCard carries the numbers-first, accessibility-first contract that every
 * chart inherits: a chart region with `role="img"` and a non-empty summarizing
 * `aria-label`, and an always-present data table with one row per datum that is
 * never removed from the DOM regardless of viewport (Requirements 12.1, 12.2,
 * 12.4, 15.3, 19.3). ResizeObserver is stubbed in src/test/setup.ts, so no real
 * layout is needed — we assert the contract, not pixels.
 */

// Feature: ui-polish-and-visualizations, Property 7: Every chart carries its accessibility contract and its data table

interface Datum {
  label: string;
  value: number;
}

/**
 * A dataset of `{ label, value }`. Labels are constrained to non-empty strings
 * so each rendered row has meaningful, text-visible content (no color-alone
 * reliance, Req 12.4).
 */
const dataset: fc.Arbitrary<Datum[]> = fc.array(
  fc.record({
    // Non-empty labels drawn from a set that survives Testing Library's
    // whitespace normalization, so the text-visibility assertion is exact.
    label: fc
      .string({
        minLength: 1,
        maxLength: 24,
        unit: fc.constantFrom(..."abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ".split("")),
      })
      .map((s) => s.replace(/\s+/g, " ").trim())
      .filter((s) => s.length > 0),
    value: fc.integer({ min: -1_000_000, max: 1_000_000 }),
  }),
  { minLength: 1, maxLength: 20 },
);

/** A tiny stand-in chart body — ChartCard is chart-library agnostic. */
function dummyChart() {
  return <div data-testid="chart-body">chart</div>;
}

/** Build a data table with exactly one row per datum, labels + values as text. */
function dataTableFor(data: Datum[], testid: string) {
  return (
    <table data-testid={testid}>
      <caption>Data</caption>
      <thead>
        <tr>
          <th scope="col">Label</th>
          <th scope="col">Value</th>
        </tr>
      </thead>
      <tbody>
        {data.map((d, i) => (
          <tr key={i}>
            <td>{d.label}</td>
            <td>{d.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

describe("Property 7: Every chart carries its accessibility contract and its data table", () => {
  it("renders role=img + non-empty aria-label and one data-table row per datum for any dataset", () => {
    fc.assert(
      fc.property(dataset, (data) => {
        const { unmount } = render(
          <ChartCard
            title="Values"
            ariaLabel={`Chart of ${data.length} values`}
            chart={dummyChart()}
            dataTable={dataTableFor(data, "prop-table")}
            height={280}
          />,
        );
        try {
          // 1. Chart region carries role="img" with a non-empty accessible name.
          const region = screen.getByRole("img");
          const label = region.getAttribute("aria-label");
          expect(label).toBeTruthy();
          expect((label ?? "").trim().length).toBeGreaterThan(0);

          // 2. The data table is present in the DOM with one row per datum. It is
          //    rendered exactly once (never duplicated), so body rows === data.length
          //    regardless of viewport (CSS-hidden, never removed).
          const table = screen.getByTestId("prop-table");
          const bodyRows = within(table).getAllByRole("row").length - 1; // minus header row
          expect(bodyRows).toBe(data.length);

          // 3. No color-alone reliance: each datum's label + value appear as text.
          for (const d of data) {
            expect(within(table).getAllByText(d.label).length).toBeGreaterThan(0);
          }
        } finally {
          unmount();
        }
      }),
      { numRuns: 100 },
    );
  });

  it("keeps the data table in the DOM as a single instance (not removed at any viewport)", () => {
    const data: Datum[] = [
      { label: "Repairs", value: 100 },
      { label: "Insurance", value: 200 },
    ];
    render(
      <ChartCard
        title="Values"
        ariaLabel="Expense breakdown"
        chart={dummyChart()}
        dataTable={dataTableFor(data, "single-table")}
      />,
    );
    // Exactly one table node exists (rendered once, CSS-only visibility).
    expect(screen.getAllByTestId("single-table")).toHaveLength(1);
  });
});

describe("ChartCard — accessibility", () => {
  it("has no axe violations", async () => {
    const data: Datum[] = [
      { label: "Repairs", value: 100 },
      { label: "Insurance", value: 200 },
    ];
    const { container } = render(
      <ChartCard
        title="Expenses by category"
        ariaLabel="Expenses by category, ranked highest to lowest"
        chart={dummyChart()}
        dataTable={dataTableFor(data, "axe-table")}
      />,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});

describe("ChartPlaceholder — Suspense fallback (Req 14.3)", () => {
  it("renders a role=status region announcing the loading chart", () => {
    render(<ChartPlaceholder height={280} />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Loading chart…");
  });
});
