import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { YearEndItemDetails } from "./YearEndItemDetails";

function renderDetails(
  itemId: string,
  details: Record<string, unknown> | null | undefined,
) {
  return render(
    <MemoryRouter>
      <YearEndItemDetails itemId={itemId} details={details} />
    </MemoryRouter>,
  );
}

describe("YearEndItemDetails", () => {
  it("renders nothing for an unknown item id", () => {
    const { container } = renderDetails("not_an_item", { income_total: "1.00" });
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for an unknown shape", () => {
    expect(renderDetails("income_entered", { other: 5 }).container).toBeEmptyDOMElement();
    expect(renderDetails("income_entered", { income_total: 5 }).container).toBeEmptyDOMElement();
    expect(renderDetails("income_entered", null).container).toBeEmptyDOMElement();
    expect(renderDetails("loan_interest_confirmed", { loans: "x" }).container).toBeEmptyDOMElement();
  });

  it("renders a known scalar as a description list with formatted money", () => {
    renderDetails("income_entered", { income_total: "1234.50" });
    expect(screen.getByText("Income total")).toBeInTheDocument();
    expect(screen.getByText(/1,234\.50/)).toBeInTheDocument();
  });
});
