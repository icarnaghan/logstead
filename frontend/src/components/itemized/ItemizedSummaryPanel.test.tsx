import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ItemizedSummary } from "../../api/itemized";
import { ItemizedSummaryPanel, sourceLabel } from "./ItemizedSummaryPanel";

function summary(over: Partial<ItemizedSummary> = {}): ItemizedSummary {
  return {
    category_id: "repairs",
    label: "Repairs",
    schedule_e_line: 14,
    tax_year: 2023,
    entered_total: null,
    entered_total_rows: [],
    itemized_sum: "0.00",
    itemized_count: 0,
    entries: [],
    remainder: null,
    line_total: "0.00",
    line_source: "none",
    total_differs_from_itemized: false,
    ...over,
  };
}

describe("sourceLabel (Req 7.5)", () => {
  it("names the line and the source", () => {
    expect(sourceLabel("entered_total", 14)).toBe("Line 14 uses: entered total");
    expect(sourceLabel("itemized", 14)).toBe("Line 14 uses: itemized entries");
    expect(sourceLabel("none", 15)).toBe("Line 15 has no amount for this year");
  });
});

describe("ItemizedSummaryPanel", () => {
  it("renders figures in cents with the count", () => {
    render(
      <ItemizedSummaryPanel
        line={14}
        summary={summary({
          entered_total: "4200.00",
          itemized_sum: "3100.00",
          itemized_count: 5,
          remainder: "1100.00",
          line_total: "4200.00",
          line_source: "entered_total",
        })}
      />,
    );
    expect(screen.getByText("Entered total").nextElementSibling).toHaveTextContent(
      "$4,200.00",
    );
    expect(screen.getByText("Itemized sum").nextElementSibling).toHaveTextContent(
      "$3,100.00 (5 entries)",
    );
    expect(
      screen.getByText("Unitemized remainder").nextElementSibling,
    ).toHaveTextContent("$1,100.00");
    expect(screen.queryByText("Over total")).not.toBeInTheDocument();
  });

  it("flags a negative remainder in text, not only color", () => {
    render(
      <ItemizedSummaryPanel
        line={14}
        summary={summary({
          entered_total: "1000.00",
          itemized_sum: "1500.00",
          itemized_count: 1,
          remainder: "-500.00",
          line_total: "1000.00",
          line_source: "entered_total",
        })}
      />,
    );
    expect(
      screen.getByText("Unitemized remainder").nextElementSibling,
    ).toHaveTextContent("-$500.00");
    expect(screen.getByText("Over total")).toBeInTheDocument();
    expect(
      screen.getByText("Itemized entries exceed the entered total"),
    ).toBeInTheDocument();
  });

  it("omits the remainder when there is no total", () => {
    render(<ItemizedSummaryPanel line={14} summary={summary()} />);
    expect(screen.queryByText("Unitemized remainder")).not.toBeInTheDocument();
    expect(screen.getByText("No total entered")).toBeInTheDocument();
    expect(
      screen.getByText("Line 14 has no amount for this year"),
    ).toBeInTheDocument();
  });
});
