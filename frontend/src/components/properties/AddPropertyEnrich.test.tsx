import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { AddPropertyDialog } from "./AddPropertyDialog";
import { ApiError } from "../../lib/apiClient";
import type { AddressSuggestion, Property } from "../../api/properties";

/**
 * Deeper add-property + enrichment flow coverage (Requirements 2.1, 2.2, 3.3,
 * 3.4, 3.6, 3.7). Complements AddPropertyDialog.test.tsx: here we assert that a
 * prefilled value stays editable before saving, that an unavailable/not_found
 * enrichment never blocks creation, and that a server 400 with a `field` is
 * rendered next to the matching input. Everything is injected — no network.
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

async function openAndSelect(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /add property/i }));
  const addressInput = await screen.findByRole("combobox", { name: /address/i });
  await user.type(addressInput, "1 Maple");
  const option = await screen.findByRole("option", { name: /1 maple st/i });
  await user.click(option);
  return addressInput;
}

describe("AddPropertyDialog — editing prefilled values (Req 3.4)", () => {
  it("lets the user edit a prefilled field before saving", async () => {
    const user = userEvent.setup();
    const enrich = vi.fn().mockResolvedValue({
      status: "found",
      details: { property_type: "single_family", formatted_address: "1 Maple St" },
    });
    const create = vi.fn().mockResolvedValue(createdProperty({ name: "Corrected Name" }));
    const onCreated = vi.fn();

    render(
      <AddPropertyDialog
        onCreated={onCreated}
        enrich={enrich}
        create={create}
        fetchSuggestions={makeSuggest([{ formatted_address: "1 Maple St" }])}
      />,
    );

    await openAndSelect(user);
    await waitFor(() => expect(enrich).toHaveBeenCalledWith("1 Maple St"));

    // The prefilled property type is present and editable.
    const typeInput = screen.getByLabelText(/property type/i);
    expect(typeInput).toHaveValue("single_family");
    await user.clear(typeInput);
    await user.type(typeInput, "condo");

    // The name is prefilled from the enriched address; overwrite it.
    const nameInput = screen.getByLabelText(/^name$/i);
    await user.clear(nameInput);
    await user.type(nameInput, "Corrected Name");

    await user.click(screen.getByRole("button", { name: /save property/i }));

    // The enriched details are persisted alongside the edited fields (Req 3.3).
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        name: "Corrected Name",
        address_text: "1 Maple St",
        property_type: "condo",
        details: { property_type: "single_family", formatted_address: "1 Maple St" },
      }),
    );
    expect(onCreated).toHaveBeenCalledOnce();
  });
});

describe("AddPropertyDialog — creation never blocked by enrichment (Req 3.7)", () => {
  it("saves successfully after an 'unavailable' enrichment", async () => {
    const user = userEvent.setup();
    const enrich = vi.fn().mockResolvedValue({
      status: "unavailable",
      message: "Property data could not be retrieved.",
    });
    const create = vi.fn().mockResolvedValue(createdProperty({ name: "Manual Rental" }));
    const onCreated = vi.fn();

    render(
      <AddPropertyDialog
        onCreated={onCreated}
        enrich={enrich}
        create={create}
        fetchSuggestions={makeSuggest([{ formatted_address: "1 Maple St" }])}
      />,
    );

    await openAndSelect(user);
    expect(await screen.findByText(/could not be retrieved/i)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/^name$/i), "Manual Rental");
    await user.click(screen.getByRole("button", { name: /save property/i }));

    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    expect(onCreated).toHaveBeenCalledOnce();
  });

  it("saves successfully after a 'not_found' enrichment", async () => {
    const user = userEvent.setup();
    const enrich = vi.fn().mockResolvedValue({
      status: "not_found",
      message: "No property data was found for this address.",
    });
    const create = vi.fn().mockResolvedValue(createdProperty({ name: "New Place" }));
    const onCreated = vi.fn();

    render(
      <AddPropertyDialog
        onCreated={onCreated}
        enrich={enrich}
        create={create}
        fetchSuggestions={makeSuggest([{ formatted_address: "1 Maple St" }])}
      />,
    );

    await openAndSelect(user);
    expect(await screen.findByText(/no property data was found/i)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/^name$/i), "New Place");
    await user.click(screen.getByRole("button", { name: /save property/i }));

    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    expect(onCreated).toHaveBeenCalledOnce();
  });
});

describe("AddPropertyDialog — server field validation (Req 2.2)", () => {
  it("renders a server 400 field=name error next to the name input", async () => {
    const user = userEvent.setup();
    const create = vi
      .fn()
      .mockRejectedValue(
        new ApiError(400, "Bad Request", {
          field: "name",
          message: "A property with this name already exists.",
        }),
      );
    const onCreated = vi.fn();

    render(
      <AddPropertyDialog
        onCreated={onCreated}
        enrich={vi.fn()}
        create={create}
        fetchSuggestions={makeSuggest([])}
      />,
    );

    await user.click(screen.getByRole("button", { name: /add property/i }));
    await user.type(
      await screen.findByRole("combobox", { name: /address/i }),
      "1 Maple St",
    );
    await user.type(screen.getByLabelText(/^name$/i), "Duplicate");
    await user.click(screen.getByRole("button", { name: /save property/i }));

    // The message renders in the element wired to the name input's
    // aria-describedby, i.e. adjacent to the offending field.
    const nameInput = screen.getByLabelText(/^name$/i);
    await waitFor(() => expect(nameInput).toHaveAttribute("aria-invalid", "true"));
    const describedBy = nameInput.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    const errorEl = document.getElementById(describedBy as string);
    expect(errorEl).toHaveTextContent(/already exists/i);

    expect(onCreated).not.toHaveBeenCalled();
  });

  it("renders a non-field 400 as a form-level alert", async () => {
    const user = userEvent.setup();
    const create = vi
      .fn()
      .mockRejectedValue(
        new ApiError(400, "Bad Request", { message: "Something was off." }),
      );

    render(
      <AddPropertyDialog
        onCreated={vi.fn()}
        enrich={vi.fn()}
        create={create}
        fetchSuggestions={makeSuggest([])}
      />,
    );

    await user.click(screen.getByRole("button", { name: /add property/i }));
    await user.type(
      await screen.findByRole("combobox", { name: /address/i }),
      "1 Maple St",
    );
    await user.type(screen.getByLabelText(/^name$/i), "Whatever");
    await user.click(screen.getByRole("button", { name: /save property/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/something was off/i);
  });
});

describe("AddPropertyDialog — accessibility (Req 14.4)", () => {
  it("the open dialog has no detectable axe violations", async () => {
    const user = userEvent.setup();
    render(
      <AddPropertyDialog
        onCreated={vi.fn()}
        enrich={vi.fn()}
        create={vi.fn()}
        fetchSuggestions={makeSuggest([])}
      />,
    );

    await user.click(screen.getByRole("button", { name: /add property/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("combobox", { name: /address/i })).toBeInTheDocument();

    const results = await axe(dialog, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
