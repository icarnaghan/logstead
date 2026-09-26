import { useEffect, useId, useRef, useState } from "react";
import {
  suggestAddresses,
  type AddressSuggestion,
} from "../../api/properties";

interface AddressAutocompleteProps {
  /** Current address text (controlled by the parent form). */
  value: string;
  /** Called on every keystroke with the new free-text value. */
  onChange: (value: string) => void;
  /**
   * Called when the user commits a suggestion (click or Enter). The parent
   * uses this to trigger RentCast enrichment for the chosen address.
   */
  onSelect: (suggestion: AddressSuggestion) => void;
  /** id used to associate an external <label> with the input. */
  id: string;
  /** id of an error message element, wired via aria-describedby when present. */
  errorId?: string;
  /** True marks the input invalid for assistive tech. */
  invalid?: boolean;
  /**
   * Injectable suggestion fetcher, primarily for tests. Defaults to the real
   * `suggestAddresses` API call.
   */
  fetchSuggestions?: (
    q: string,
    signal?: AbortSignal,
  ) => Promise<AddressSuggestion[]>;
  /** Debounce window in ms before a suggestion request fires. */
  debounceMs?: number;
}

/**
 * Accessible address input with autocomplete (Requirement 3.1).
 *
 * Implements the WAI-ARIA combobox pattern: a text input with
 * `role="combobox"` owning a `role="listbox"` popup of suggestions. Typing
 * debounces a call to the address provider; results render as selectable
 * `role="option"` items. Full keyboard support is provided — ArrowDown/ArrowUp
 * move the active option (tracked with `aria-activedescendant`), Enter commits
 * it, and Escape dismisses the list — so the flow never requires a pointer.
 *
 * Autocomplete is a convenience and never gates creation: a provider failure
 * simply yields no suggestions and the user can type the address manually.
 */
export function AddressAutocomplete({
  value,
  onChange,
  onSelect,
  id,
  errorId,
  invalid,
  fetchSuggestions = suggestAddresses,
  debounceMs = 250,
}: AddressAutocompleteProps) {
  const listboxId = useId();
  const optionIdPrefix = useId();
  const [suggestions, setSuggestions] = useState<AddressSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  // Suppresses the next fetch after a programmatic value change (selection).
  const skipNextFetch = useRef(false);

  useEffect(() => {
    if (skipNextFetch.current) {
      skipNextFetch.current = false;
      return;
    }
    const query = value.trim();
    if (query.length < 3) {
      setSuggestions([]);
      setOpen(false);
      return;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => {
      fetchSuggestions(query, controller.signal)
        .then((results) => {
          setSuggestions(results);
          setOpen(results.length > 0);
          setActiveIndex(-1);
        })
        .catch(() => {
          // Autocomplete degrades silently; manual entry always remains.
          setSuggestions([]);
          setOpen(false);
        });
    }, debounceMs);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [value, fetchSuggestions, debounceMs]);

  function commit(suggestion: AddressSuggestion) {
    skipNextFetch.current = true;
    onChange(suggestion.formatted_address);
    setSuggestions([]);
    setOpen(false);
    setActiveIndex(-1);
    onSelect(suggestion);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || suggestions.length === 0) {
      if (event.key === "ArrowDown" && suggestions.length > 0) {
        setOpen(true);
        setActiveIndex(0);
        event.preventDefault();
      }
      return;
    }

    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        setActiveIndex((i) => (i + 1) % suggestions.length);
        break;
      case "ArrowUp":
        event.preventDefault();
        setActiveIndex((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
        break;
      case "Enter":
        if (activeIndex >= 0 && activeIndex < suggestions.length) {
          event.preventDefault();
          commit(suggestions[activeIndex]);
        }
        break;
      case "Escape":
        event.preventDefault();
        setOpen(false);
        setActiveIndex(-1);
        break;
      default:
        break;
    }
  }

  const activeOptionId =
    open && activeIndex >= 0 ? `${optionIdPrefix}-${activeIndex}` : undefined;

  return (
    <div className="relative">
      <input
        id={id}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={activeOptionId}
        aria-invalid={invalid || undefined}
        aria-describedby={errorId}
        autoComplete="off"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => {
          // Delay so an option click registers before the list unmounts.
          setTimeout(() => setOpen(false), 120);
        }}
        className="w-full rounded-md border border-border px-3 py-2 text-sm text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      />
      <ul
        id={listboxId}
        role="listbox"
        aria-label="Address suggestions"
        className={
          open && suggestions.length > 0
            ? "absolute z-10 mt-1 w-full overflow-hidden rounded-md border border-border bg-surface shadow-lg"
            : "hidden"
        }
      >
        {suggestions.map((suggestion, index) => (
          <li
            key={suggestion.provider_place_id ?? suggestion.formatted_address}
            id={`${optionIdPrefix}-${index}`}
            role="option"
            aria-selected={index === activeIndex}
            // onMouseDown (not onClick) so it fires before the input's blur.
            onMouseDown={(e) => {
              e.preventDefault();
              commit(suggestion);
            }}
            className={[
              "cursor-pointer px-3 py-2 text-sm",
              index === activeIndex
                ? "bg-accent text-accent-fg"
                : "text-fg-muted hover:bg-surface-muted",
            ].join(" ")}
          >
            {suggestion.formatted_address}
          </li>
        ))}
      </ul>
    </div>
  );
}
