import { render, screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { ChartCard } from "./ChartCard";
import NetByPropertyChart, {
  NetByPropertyTable,
} from "./NetByPropertyChart";
import { netByProperty, type PropertyNetDatum } from "./prepare";
import { ThemeProvider } from "../../theme/ThemeProvider";

/**
 * Component tests for the ranked net-by-property chart + its always-present
 * data table (task 17.5, Requirements 18.1, 18.2, 12.1, 12.2, 12.4).
 *
 * The chart is rendered NON-lazily (imported directly) inside a `ChartCard` so
 * we assert the accessibility contract (`role="img"` + `aria-label`) and the
 * data-table contract (one row per property, formatted amounts, descending
 * order, textual loss cue) without Suspense timing. `ResizeObserver` is stubbed
 * globally in `src/test/setup.ts`, and `useChartColors` subscribes to the theme
 * so the chart is wrapped in a `ThemeProvider`.
 */

// Deliberately unsorted input: the builder ranks it descending (Req 18.2).
const DATA: PropertyNetDatum[] = netByProperty([
  { property_id: "p2", property_name: "Oak Cottage", total_income: "0.00", total_expenses: "800.00", net: "-800.00" },
  { property_id: "p1", property_name: "Maple Duplex", total_income: "1500.00", total_expenses: "250.00", net: "1250.00" },
  { property_id: "p3", property_name: "Birch Bungalow", total_income: "600.00", total_expenses: "100.00", net: "500.00" },
]);

function renderCard(data: PropertyNetDatum[] = DATA) {
  return render(
    <ThemeProvider>
      <ChartCard
        title="Net contribution by property"
        ariaLabel="Net contribution by property, ranked from highest to lowest"
        chart={<NetByPropertyChart data={data} />}
        dataTable={<NetByPropertyTable data={data} />}
      />
    </ThemeProvider>,
  );
}

describe("NetByPropertyChart — accessibility contract (Req 12.1, 12.2)", () => {
  it("renders a role=img chart region with a non-empty aria-label", () => {
    renderCard();
    const region = screen.getByRole("img");
    expect((region.getAttribute("aria-label") ?? "").trim().length).toBeGreaterThan(
      0,
    );
  });
});

describe("NetByPropertyTable — always-present data table (Req 18.1, 18.2)", () => {
  it("renders one row per property with formatted amounts", () => {
    render(<NetByPropertyTable data={DATA} />);
    const table = screen.getByRole("table");
    const bodyRows = within(table).getAllByRole("row").slice(1); // drop header
    expect(bodyRows).toHaveLength(DATA.length);

    expect(within(table).getByText("Maple Duplex")).toBeInTheDocument();
    expect(within(table).getByText("$1,250.00")).toBeInTheDocument();
    expect(within(table).getByText("Birch Bungalow")).toBeInTheDocument();
    expect(within(table).getByText("$500.00")).toBeInTheDocument();
    expect(within(table).getByText("Oak Cottage")).toBeInTheDocument();
    expect(within(table).getByText("-$800.00")).toBeInTheDocument();
  });

  it("ranks rows by descending net (Req 18.2)", () => {
    render(<NetByPropertyTable data={DATA} />);
    const table = screen.getByRole("table");
    const rowHeaders = within(table)
      .getAllByRole("rowheader")
      .map((cell) => cell.textContent);
    expect(rowHeaders).toEqual(["Maple Duplex", "Birch Bungalow", "Oak Cottage"]);
  });

  it("carries a textual loss cue for a negative net (Req 12.4)", () => {
    render(<NetByPropertyTable data={DATA} />);
    expect(screen.getByText(/\(loss\)/i)).toBeInTheDocument();
  });

  it("shows an empty note when there are no properties", () => {
    render(<NetByPropertyTable data={[]} />);
    expect(
      screen.getByText(/no properties have any activity/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("NetByPropertyChart — theme re-render keeps the chart present (Req 11.3)", () => {
  it("keeps the chart region present after a theme re-render", () => {
    const { container, rerender } = renderCard();
    expect(within(container).getByRole("img")).toBeInTheDocument();

    rerender(
      <ThemeProvider>
        <ChartCard
          title="Net contribution by property"
          ariaLabel="Net contribution by property, ranked from highest to lowest"
          chart={<NetByPropertyChart data={DATA} />}
          dataTable={<NetByPropertyTable data={DATA} />}
        />
      </ThemeProvider>,
    );
    expect(within(container).getByRole("img")).toBeInTheDocument();
  });
});

describe("NetByPropertyChart — accessibility (axe)", () => {
  it("has no automatically detectable a11y violations", async () => {
    const { container } = renderCard();
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
