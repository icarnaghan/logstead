import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PropertyDetailsView } from "./PropertyDetailsView";
import type { PropertyDetails } from "../../api/properties";

/**
 * Component tests for the rich property-details display (Requirements 3.3, 3.8,
 * 12.1). Asserts feature booleans render as Yes/No (never the raw boolean),
 * money renders formatted from its two-decimal string, the latest tax
 * assessment year is shown, and sparse records only render what is present.
 */

function richDetails(): PropertyDetails {
  return {
    property_type: "Single Family",
    bedrooms: 3,
    bathrooms: "2.5",
    year_built: 1995,
    zoning: "R1",
    subdivision: "Sunset",
    last_sale_date: "2019-06-15",
    last_sale_price: "415000.00",
    features: {
      roof_type: "Shingle",
      heating: true,
      heating_type: "Forced Air",
      cooling: false,
      garage: true,
      garage_spaces: 2,
    },
    hoa: { fee: "150.00" },
    tax_assessments: [
      { year: 2021, value: "380000.00" },
      { year: 2022, value: "400000.00", land: "95000.00", improvements: "305000.00" },
    ],
  };
}

describe("PropertyDetailsView", () => {
  it("renders structure, features, and sale/tax fields", () => {
    render(<PropertyDetailsView details={richDetails()} />);

    expect(screen.getByText("Single Family")).toBeInTheDocument();
    expect(screen.getByText("1995")).toBeInTheDocument();
    expect(screen.getByText("R1")).toBeInTheDocument();
    expect(screen.getByText("Shingle")).toBeInTheDocument();
    expect(screen.getByText("Forced Air")).toBeInTheDocument();
    expect(screen.getByText("2019-06-15")).toBeInTheDocument();
  });

  it("renders feature booleans as Yes/No, never the raw boolean", () => {
    render(<PropertyDetailsView details={richDetails()} />);

    // heating: true -> Yes; cooling: false -> No.
    const heatingLabel = screen.getByText("Heating");
    expect(heatingLabel.nextElementSibling).toHaveTextContent("Yes");
    const coolingLabel = screen.getByText("Cooling");
    expect(coolingLabel.nextElementSibling).toHaveTextContent("No");
    // The literal string "true"/"false" must never appear.
    expect(screen.queryByText("true")).not.toBeInTheDocument();
    expect(screen.queryByText("false")).not.toBeInTheDocument();
  });

  it("formats money from the two-decimal string values", () => {
    render(<PropertyDetailsView details={richDetails()} />);

    expect(screen.getByText("$415,000.00")).toBeInTheDocument();
    expect(screen.getByText("$150.00")).toBeInTheDocument();
  });

  it("shows the latest tax assessment year", () => {
    render(<PropertyDetailsView details={richDetails()} />);

    // Latest is 2022, not 2021.
    expect(screen.getByText(/Tax assessment \(2022\)/)).toBeInTheDocument();
    expect(screen.queryByText(/Tax assessment \(2021\)/)).not.toBeInTheDocument();
    expect(screen.getByText("$400,000.00")).toBeInTheDocument();
  });

  it("renders only present fields for a sparse record", () => {
    render(<PropertyDetailsView details={{ city: "Austin", bedrooms: 2 }} />);

    expect(screen.getByText("2")).toBeInTheDocument();
    // Absent fields produce no rows.
    expect(screen.queryByText("Heating")).not.toBeInTheDocument();
    expect(screen.queryByText("Last sale price")).not.toBeInTheDocument();
    expect(screen.queryByText(/Tax assessment/)).not.toBeInTheDocument();
  });
});
