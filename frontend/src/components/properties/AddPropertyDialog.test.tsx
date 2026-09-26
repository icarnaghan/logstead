import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AddPropertyDialog } from "./AddPropertyDialog";
import type { AddressSuggestion, Property } from "../../api/properties";

/**
 * Component tests for the add-property enrichment flow (Requirements 2.1, 2.2,
 * 3.1, 3.3, 3.5, 3.6, 3.7).
 */

function makeSuggest(results: AddressSuggestion[]) {
  return vi.fn(() => Promise.resolve(results));
}

function createdProperty(overrides: Partial<Property> = {}): Property {
  return {
    id: "p1",
    user_id: "u1",
    name: "1 Maple St",
    address_text: "1 Maple St",
    ...overrides,
  };
}

async function openDialogAndSelectAddress(
  user: ReturnType<typeof userEvent.setup>,
) {
  await user.click(screen.getByRole("button", { name: /add property/i }));
  const addressInput = await screen.findByRole("combobox", { name: /address/i });
  await user.type(addressInput, "1 Maple");
  const option = await screen.findByRole("option", { name: /1 maple st/i });
  await user.click(option);
  return addressInput;
}

describe("AddPropertyDialog — enrich found", () => {
  it("prefills editable detail fields when enrichment returns found", async () => {
    const user = userEvent.setup();
    const enrich = vi.fn().mockResolvedValue({
      status: "found",
      details: { property_type: "single_family", formatted_address: "1 Maple St" },
    });
    const create = vi.fn().mockResolvedValue(createdProperty());

    render(
      <AddPropertyDialog
        onCreated={vi.fn()}
        enrich={enrich}
        create={create}
        fetchSuggestions={makeSuggest([{ formatted_address: "1 Maple St" }])}
      />,
    );

    await openDialogAndSelectAddress(user);

    await waitFor(() => expect(enrich).toHaveBeenCalledWith("1 Maple St"));
    // Found message and prefilled, editable property type.
    expect(await screen.findByText(/property details found/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/property type/i)).toHaveValue("single_family");
    // The address field is committed from the selected suggestion.
    expect(screen.getByRole("combobox", { name: /address/i })).toHaveValue(
      "1 Maple St",
    );
  });
});

describe("AddPropertyDialog — enrich unavailable (manual entry)", () => {
  it("shows the unavailable message but still allows manual creation", async () => {
    const user = userEvent.setup();
    const enrich = vi.fn().mockResolvedValue({
      status: "unavailable",
      message: "Property data could not be retrieved.",
    });
    const create = vi.fn().mockResolvedValue(createdProperty({ name: "My Rental" }));
    const onCreated = vi.fn();

    render(
      <AddPropertyDialog
        onCreated={onCreated}
        enrich={enrich}
        create={create}
        fetchSuggestions={makeSuggest([{ formatted_address: "1 Maple St" }])}
      />,
    );

    await openDialogAndSelectAddress(user);

    expect(
      await screen.findByText(/could not be retrieved/i),
    ).toBeInTheDocument();

    // Manual entry: fill the name and save. Enrichment failure must not block.
    await user.type(screen.getByLabelText(/^name$/i), "My Rental");
    await user.click(screen.getByRole("button", { name: /save property/i }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        name: "My Rental",
        address_text: "1 Maple St",
        property_type: null,
      }),
    );
    expect(onCreated).toHaveBeenCalledOnce();
  });

  it("shows a not_found message and allows manual entry", async () => {
    const user = userEvent.setup();
    const enrich = vi.fn().mockResolvedValue({
      status: "not_found",
      message: "No property data was found for this address.",
    });

    render(
      <AddPropertyDialog
        onCreated={vi.fn()}
        enrich={enrich}
        create={vi.fn().mockResolvedValue(createdProperty())}
        fetchSuggestions={makeSuggest([{ formatted_address: "1 Maple St" }])}
      />,
    );

    await openDialogAndSelectAddress(user);

    expect(await screen.findByText(/no property data was found/i)).toBeInTheDocument();
  });
});

describe("AddPropertyDialog — unit picker (secondary addresses)", () => {
  it("fetches units after selecting a building and renders the Unit picker", async () => {
    const user = userEvent.setup();
    const enrich = vi.fn().mockResolvedValue({ status: "not_found", message: "no data" });
    const fetchUnits = vi.fn().mockResolvedValue([
      {
        formatted_address: "1 Maple St Unit A, Springfield, IL",
        provider_place_id: "unit-a",
      },
      {
        formatted_address: "1 Maple St Unit B, Springfield, IL",
        provider_place_id: "unit-b",
      },
    ]);

    render(
      <AddPropertyDialog
        onCreated={vi.fn()}
        enrich={enrich}
        create={vi.fn().mockResolvedValue(createdProperty())}
        fetchSuggestions={makeSuggest([{ formatted_address: "1 Maple St" }])}
        fetchUnits={fetchUnits}
      />,
    );

    await openDialogAndSelectAddress(user);

    await waitFor(() => expect(fetchUnits).toHaveBeenCalledWith("1 Maple St"));

    const unitSelect = await screen.findByRole("combobox", { name: /unit/i });
    expect(unitSelect).toBeInTheDocument();
    // The picker offers a "No specific unit" default plus each unit.
    expect(
      screen.getByRole("option", { name: /no specific unit/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /1 maple st unit a/i }),
    ).toBeInTheDocument();
  });

  it("sets the full unit address and re-enriches when a unit is chosen", async () => {
    const user = userEvent.setup();
    const enrich = vi.fn().mockResolvedValue({ status: "not_found", message: "no data" });
    const create = vi.fn().mockResolvedValue(createdProperty());
    const fetchUnits = vi.fn().mockResolvedValue([
      {
        formatted_address: "1 Maple St Unit A, Springfield, IL",
        provider_place_id: "unit-a",
      },
    ]);

    render(
      <AddPropertyDialog
        onCreated={vi.fn()}
        enrich={enrich}
        create={create}
        fetchSuggestions={makeSuggest([{ formatted_address: "1 Maple St" }])}
        fetchUnits={fetchUnits}
      />,
    );

    await openDialogAndSelectAddress(user);

    const unitSelect = await screen.findByRole("combobox", { name: /unit/i });
    await user.selectOptions(unitSelect, "1 Maple St Unit A, Springfield, IL");

    // Re-enrichment runs on the chosen full unit address.
    await waitFor(() =>
      expect(enrich).toHaveBeenLastCalledWith("1 Maple St Unit A, Springfield, IL"),
    );

    // The chosen unit becomes the saved address on submit.
    await user.type(screen.getByLabelText(/^name$/i), "Unit A");
    await user.click(screen.getByRole("button", { name: /save property/i }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        name: "Unit A",
        address_text: "1 Maple St Unit A, Springfield, IL",
        property_type: null,
      }),
    );
  });

  it("shows no Unit picker when the building has no secondary addresses", async () => {
    const user = userEvent.setup();

    render(
      <AddPropertyDialog
        onCreated={vi.fn()}
        enrich={vi.fn().mockResolvedValue({ status: "not_found", message: "no data" })}
        create={vi.fn().mockResolvedValue(createdProperty())}
        fetchSuggestions={makeSuggest([{ formatted_address: "1 Maple St" }])}
        fetchUnits={vi.fn().mockResolvedValue([])}
      />,
    );

    await openDialogAndSelectAddress(user);
    await waitFor(() =>
      expect(screen.getByText(/you can still save the property/i)).toBeInTheDocument(),
    );

    expect(screen.queryByRole("combobox", { name: /unit/i })).not.toBeInTheDocument();
  });
});

describe("AddPropertyDialog — validation", () => {
  it("blocks submission and shows a field error when name is blank", async () => {
    const user = userEvent.setup();
    const create = vi.fn();

    render(
      <AddPropertyDialog
        onCreated={vi.fn()}
        enrich={vi.fn()}
        create={create}
        fetchSuggestions={makeSuggest([])}
      />,
    );

    await user.click(screen.getByRole("button", { name: /add property/i }));
    // Fill only the address, leave name blank.
    await user.type(
      await screen.findByRole("combobox", { name: /address/i }),
      "1 Maple St",
    );
    await user.click(screen.getByRole("button", { name: /save property/i }));

    expect(await screen.findByText(/name is required/i)).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });
});
