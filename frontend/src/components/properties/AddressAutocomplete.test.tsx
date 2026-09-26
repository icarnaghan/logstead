import { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { AddressAutocomplete } from "./AddressAutocomplete";
import type { AddressSuggestion } from "../../api/properties";

/**
 * Component tests for the accessible address combobox (Requirement 3.1).
 *
 * Exercises the WAI-ARIA combobox pattern end to end without any network:
 * `fetchSuggestions` is always injected, and a short `debounceMs` keeps the
 * debounce window observable but fast. Covers debounced fetch + listbox open,
 * ArrowDown/ArrowUp active-descendant movement, Enter commit, Escape dismiss,
 * silent degradation on provider failure, and re-fetch suppression after a
 * selection.
 */

const SUGGESTIONS: AddressSuggestion[] = [
  { formatted_address: "1 Maple St, Springfield", provider_place_id: "a" },
  { formatted_address: "12 Maple Ave, Shelbyville", provider_place_id: "b" },
  { formatted_address: "123 Maple Ct, Ogdenville", provider_place_id: "c" },
];

function makeFetch(results: AddressSuggestion[] = SUGGESTIONS) {
  // Declare the fetch signature so `.mock.calls[n][0]` is a typed tuple element
  // under `tsc -b` (an argless mock types calls as an empty tuple).
  return vi.fn((_q: string, _signal?: AbortSignal) => Promise.resolve(results));
}

/**
 * Controlled harness: mirrors how AddPropertyDialog drives the combobox, so the
 * `value`/`onChange` contract (including committing a selected address into the
 * input) is exercised the way it works in production.
 */
function Harness({
  fetchSuggestions,
  onSelect = vi.fn(),
  debounceMs = 10,
}: {
  fetchSuggestions: (
    q: string,
    signal?: AbortSignal,
  ) => Promise<AddressSuggestion[]>;
  onSelect?: (s: AddressSuggestion) => void;
  debounceMs?: number;
}) {
  const [value, setValue] = useState("");
  return (
    <div>
      <label htmlFor="addr">Address</label>
      <AddressAutocomplete
        id="addr"
        value={value}
        onChange={setValue}
        onSelect={onSelect}
        fetchSuggestions={fetchSuggestions}
        debounceMs={debounceMs}
      />
    </div>
  );
}

describe("AddressAutocomplete — debounced fetch and listbox", () => {
  it("does not fetch until at least 3 characters are typed", async () => {
    const user = userEvent.setup();
    const fetchSuggestions = makeFetch();
    render(<Harness fetchSuggestions={fetchSuggestions} />);

    const input = screen.getByRole("combobox", { name: /address/i });
    await user.type(input, "1M");

    // Under the 3-char threshold: no request, no listbox.
    await new Promise((r) => setTimeout(r, 40));
    expect(fetchSuggestions).not.toHaveBeenCalled();
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("debounces a single fetch and opens a listbox of options", async () => {
    const user = userEvent.setup();
    const fetchSuggestions = makeFetch();
    render(<Harness fetchSuggestions={fetchSuggestions} />);

    const input = screen.getByRole("combobox", { name: /address/i });
    await user.type(input, "Maple");

    // Options render only once the debounced fetch resolves and the list opens.
    const options = await screen.findAllByRole("option");
    expect(options).toHaveLength(SUGGESTIONS.length);
    expect(input).toHaveAttribute("aria-expanded", "true");
    // They live inside the named listbox.
    const listbox = screen.getByRole("listbox", { name: /address suggestions/i });
    expect(within(listbox).getAllByRole("option")).toHaveLength(SUGGESTIONS.length);

    // The debounce collapses the burst of keystrokes into a single call whose
    // final query is the full typed value.
    await waitFor(() => expect(fetchSuggestions).toHaveBeenCalled());
    const lastCall = fetchSuggestions.mock.calls.at(-1);
    expect(lastCall?.[0]).toBe("Maple");
  });
});

describe("AddressAutocomplete — keyboard navigation", () => {
  it("moves aria-activedescendant with ArrowDown/ArrowUp and wraps", async () => {
    const user = userEvent.setup();
    render(<Harness fetchSuggestions={makeFetch()} />);

    const input = screen.getByRole("combobox", { name: /address/i });
    await user.type(input, "Maple");
    const options = await screen.findAllByRole("option");

    // ArrowDown activates the first option.
    await user.keyboard("{ArrowDown}");
    expect(input).toHaveAttribute("aria-activedescendant", options[0].id);
    expect(options[0]).toHaveAttribute("aria-selected", "true");

    // Two more downs land on the last option.
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(input).toHaveAttribute("aria-activedescendant", options[2].id);

    // ArrowDown from the last option wraps to the first.
    await user.keyboard("{ArrowDown}");
    expect(input).toHaveAttribute("aria-activedescendant", options[0].id);

    // ArrowUp from the first option wraps to the last.
    await user.keyboard("{ArrowUp}");
    expect(input).toHaveAttribute("aria-activedescendant", options[2].id);
  });

  it("commits the active option on Enter: calls onSelect and sets the input", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Harness fetchSuggestions={makeFetch()} onSelect={onSelect} />);

    const input = screen.getByRole("combobox", { name: /address/i });
    await user.type(input, "Maple");
    await screen.findAllByRole("option");

    await user.keyboard("{ArrowDown}{ArrowDown}"); // second option
    await user.keyboard("{Enter}");

    expect(onSelect).toHaveBeenCalledWith(SUGGESTIONS[1]);
    expect(input).toHaveValue(SUGGESTIONS[1].formatted_address);
    // The list closes on commit.
    await waitFor(() =>
      expect(screen.queryByRole("option")).not.toBeInTheDocument(),
    );
    expect(input).toHaveAttribute("aria-expanded", "false");
  });

  it("dismisses the listbox on Escape without committing", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Harness fetchSuggestions={makeFetch()} onSelect={onSelect} />);

    const input = screen.getByRole("combobox", { name: /address/i });
    await user.type(input, "Maple");
    await screen.findAllByRole("option");

    await user.keyboard("{ArrowDown}");
    await user.keyboard("{Escape}");

    // Escape collapses the popup: the combobox reports collapsed and the
    // listbox is hidden (no active descendant). Nothing is committed.
    await waitFor(() =>
      expect(input).toHaveAttribute("aria-expanded", "false"),
    );
    expect(input).not.toHaveAttribute("aria-activedescendant");
    const listbox = screen.getByRole("listbox", { name: /address suggestions/i });
    expect(listbox).toHaveClass("hidden");
    expect(onSelect).not.toHaveBeenCalled();
  });
});

describe("AddressAutocomplete — commit by pointer", () => {
  it("commits a clicked suggestion (onSelect + input value)", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Harness fetchSuggestions={makeFetch()} onSelect={onSelect} />);

    const input = screen.getByRole("combobox", { name: /address/i });
    await user.type(input, "Maple");
    const option = await screen.findByRole("option", {
      name: SUGGESTIONS[0].formatted_address,
    });
    await user.click(option);

    expect(onSelect).toHaveBeenCalledWith(SUGGESTIONS[0]);
    expect(input).toHaveValue(SUGGESTIONS[0].formatted_address);
  });
});

describe("AddressAutocomplete — resilience", () => {
  it("degrades to no suggestions when the provider fails (never throws)", async () => {
    const user = userEvent.setup();
    const fetchSuggestions = vi.fn(() =>
      Promise.reject(new Error("provider down")),
    );
    render(<Harness fetchSuggestions={fetchSuggestions} />);

    const input = screen.getByRole("combobox", { name: /address/i });
    await user.type(input, "Maple");

    await waitFor(() => expect(fetchSuggestions).toHaveBeenCalled());
    // No listbox opens and manual entry is preserved.
    await new Promise((r) => setTimeout(r, 40));
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(input).toHaveValue("Maple");
  });

  it("suppresses the immediate re-fetch after selecting a suggestion", async () => {
    const user = userEvent.setup();
    const fetchSuggestions = makeFetch();
    render(<Harness fetchSuggestions={fetchSuggestions} />);

    const input = screen.getByRole("combobox", { name: /address/i });
    await user.type(input, "Maple");
    await screen.findAllByRole("option");

    const callsBeforeCommit = fetchSuggestions.mock.calls.length;

    // Commit the first suggestion. This programmatically changes `value`, which
    // must NOT trigger a fresh fetch for the just-selected text.
    await user.keyboard("{ArrowDown}{Enter}");

    // Give any (unwanted) debounced fetch time to fire.
    await new Promise((r) => setTimeout(r, 40));
    expect(fetchSuggestions.mock.calls.length).toBe(callsBeforeCommit);
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });
});

describe("AddressAutocomplete — accessibility (Req 14.4)", () => {
  it("exposes combobox semantics and has no detectable axe violations", async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness fetchSuggestions={makeFetch()} />);

    const input = screen.getByRole("combobox", { name: /address/i });
    expect(input).toHaveAttribute("aria-autocomplete", "list");
    expect(input).toHaveAttribute("aria-expanded", "false");

    await user.type(input, "Maple");
    await screen.findByRole("listbox", { name: /address suggestions/i });
    await user.keyboard("{ArrowDown}");

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
