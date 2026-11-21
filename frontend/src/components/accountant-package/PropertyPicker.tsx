export interface PickableProperty {
  readonly id: string;
  readonly name: string;
}

export interface PropertyPickerProps {
  properties: readonly PickableProperty[];
  /** Ids of the checked properties. */
  selectedIds: readonly string[];
  onChange: (selectedIds: string[]) => void;
  disabled?: boolean;
}

/**
 * Checkbox list of properties inside a `fieldset` with a `legend`. The caller
 * owns the selection state and starts with every property checked.
 */
export function PropertyPicker({
  properties,
  selectedIds,
  onChange,
  disabled = false,
}: PropertyPickerProps) {
  const selected = new Set(selectedIds);

  const toggle = (id: string, checked: boolean) => {
    const next = new Set(selected);
    if (checked) next.add(id);
    else next.delete(id);
    onChange(properties.filter((p) => next.has(p.id)).map((p) => p.id));
  };

  return (
    <fieldset className="min-w-0" disabled={disabled}>
      <legend className="text-sm font-medium text-fg">Properties to include</legend>
      <ul className="mt-2 space-y-1">
        {properties.map((property) => {
          const inputId = `package-property-${property.id}`;
          return (
            <li key={property.id} className="flex items-center gap-2 max-md:min-h-11">
              <input
                id={inputId}
                type="checkbox"
                className="h-4 w-4 accent-accent"
                checked={selected.has(property.id)}
                onChange={(event) => toggle(property.id, event.target.checked)}
              />
              <label htmlFor={inputId} className="text-sm text-fg">
                {property.name}
              </label>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}
