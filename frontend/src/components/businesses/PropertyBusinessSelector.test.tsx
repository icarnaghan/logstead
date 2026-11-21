import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PropertyBusinessSelector } from "./PropertyBusinessSelector";
import type { Business } from "../../api/businesses";

function biz(id: string, legalName: string): Business {
  return {
    id,
    user_id: "user-1",
    legal_name: legalName,
    entity_type: "llc",
    tax_year_end: "12-31",
  };
}

const BUSINESSES: Business[] = [
  biz("b1", "Acme Holdings LLC"),
  biz("b2", "Beacon Partners LLC"),
];

function makeSeams(businesses: Business[] = BUSINESSES) {
  return {
    loadBusinesses: vi.fn(async () => [...businesses]),
    setLink: vi.fn(async () => undefined),
  };
}

describe("PropertyBusinessSelector — set/change (Req 9, 11.5)", () => {
  it("selecting a business calls setPropertyBusiness with that businessId", async () => {
    const user = userEvent.setup();
    const seams = makeSeams();
    render(
      <PropertyBusinessSelector
        propertyId="p1"
        businessId={null}
        loadBusinesses={seams.loadBusinesses}
        setLink={seams.setLink}
      />,
    );

    // Wait for the options to populate from the loader.
    await screen.findByRole("option", { name: "Acme Holdings LLC" });

    const select = screen.getByLabelText("Owning business");
    await user.selectOptions(select, "b1");

    await waitFor(() => {
      expect(seams.setLink).toHaveBeenCalledWith("p1", "b1");
    });
  });
});

describe("PropertyBusinessSelector — clear (Req 9.3)", () => {
  it('selecting "No business" calls setPropertyBusiness with null', async () => {
    const user = userEvent.setup();
    const seams = makeSeams();
    render(
      <PropertyBusinessSelector
        propertyId="p1"
        businessId="b1"
        currentBusinessName="Acme Holdings LLC"
        loadBusinesses={seams.loadBusinesses}
        setLink={seams.setLink}
      />,
    );

    await screen.findByRole("option", { name: "Beacon Partners LLC" });

    const select = screen.getByLabelText("Owning business");
    await user.selectOptions(select, "");

    await waitFor(() => {
      expect(seams.setLink).toHaveBeenCalledWith("p1", null);
    });
  });
});

describe("PropertyBusinessSelector — current link display (Req 10.1, 10.3)", () => {
  it("shows the currently-linked business name, not a raw id", async () => {
    const seams = makeSeams();
    render(
      <PropertyBusinessSelector
        propertyId="p1"
        businessId="b1"
        currentBusinessName="Acme Holdings LLC"
        loadBusinesses={seams.loadBusinesses}
        setLink={seams.setLink}
      />,
    );

    // The resolved legal_name is shown...
    expect(await screen.findByText("Acme Holdings LLC")).toBeInTheDocument();
    // ...and the raw id never appears as user-facing text.
    expect(screen.queryByText("b1")).not.toBeInTheDocument();
  });

  it("resolves the linked name from the loaded list when no name prop is given", async () => {
    const seams = makeSeams();
    render(
      <PropertyBusinessSelector
        propertyId="p1"
        businessId="b2"
        loadBusinesses={seams.loadBusinesses}
        setLink={seams.setLink}
      />,
    );

    // Once the list loads, the name for b2 resolves into the display.
    expect(
      await screen.findByText("Beacon Partners LLC", { selector: "span" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("b2")).not.toBeInTheDocument();
  });
});

describe("PropertyBusinessSelector — accessibility (Req 12.4)", () => {
  it("has a labelled select and no detectable axe violations", async () => {
    const seams = makeSeams();
    const { container } = render(
      <PropertyBusinessSelector
        propertyId="p1"
        businessId="b1"
        currentBusinessName="Acme Holdings LLC"
        loadBusinesses={seams.loadBusinesses}
        setLink={seams.setLink}
      />,
    );

    await screen.findByRole("option", { name: "Acme Holdings LLC" });

    expect(screen.getByLabelText("Owning business").tagName).toBe("SELECT");

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});

beforeEach(() => {
  vi.restoreAllMocks();
});
