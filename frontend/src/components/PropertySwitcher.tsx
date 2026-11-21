import { useId, type ChangeEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { propertyIdFromPath, switchPropertyPath } from "./propertySwitch";
import { useShellProperties } from "./ShellPropertiesContext";
import { Select, Skeleton } from "./ui";

/** Minimum number of properties before the switcher is worth showing. */
export const PROPERTY_SWITCHER_MIN = 1;

/**
 * Header control for changing the current property (Requirement 19).
 * Native select (D13): keyboard operable with an accessible name.
 */
export function PropertySwitcher({ className }: { className?: string }) {
  const { properties, status } = useShellProperties();
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const id = useId();

  if (status === "loading") {
    return <Skeleton className={`h-9 w-40 ${className ?? ""}`} />;
  }
  if (status === "error" || properties.length < PROPERTY_SWITCHER_MIN) {
    return null;
  }

  const currentId = propertyIdFromPath(pathname);
  const hasCurrent =
    currentId !== null && properties.some((p) => p.id === currentId);

  function handleChange(event: ChangeEvent<HTMLSelectElement>) {
    const next = event.target.value;
    if (!next) return;
    navigate(switchPropertyPath(pathname, search, next));
  }

  return (
    <div className={className}>
      <label htmlFor={id} className="sr-only">
        Switch property
      </label>
      <Select
        id={id}
        value={hasCurrent ? currentId : ""}
        onChange={handleChange}
        className="max-w-[16rem] max-md:min-h-11"
      >
        {!hasCurrent && (
          <option value="" disabled>
            Switch property
          </option>
        )}
        {properties.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </Select>
    </div>
  );
}
