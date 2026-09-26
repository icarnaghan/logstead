import { NavLink } from "react-router-dom";
import { PROPERTY_NAV, propertyPath } from "./navConfig";
import { usePropertyContext } from "./PropertyLayout";
import { Breadcrumb, type Crumb } from "./ui";

interface PropertySectionProps {
  /**
   * The selected property's id. Optional — when omitted it is read from the
   * shared property context. Used only to build the sub-navigation and
   * breadcrumb ancestor paths, never displayed as user-facing content.
   */
  propertyId?: string;
  /** Page heading for this sub-section. */
  title: string;
  /** Short descriptive text under the heading. */
  description: string;
}

/**
 * Resolve the human-readable property name from the shared context, never
 * leaking the raw identifier (Requirements 2.1, 3.1).
 *
 * - `"loaded"` → the property's name.
 * - `"loading"` → a neutral placeholder while the fetch is in flight.
 * - `"error"` (or any missing name) → a neutral "Property" fallback.
 */
function resolvePropertyName(
  status: "loading" | "loaded" | "error",
  name: string | undefined,
): string {
  if (status === "loading") return "Loading property…";
  if (status === "loaded" && name) return name;
  return "Property";
}

/**
 * Shared layout for the per-property sub-sections (Transactions, Depreciable
 * Assets, Schedule E Report).
 *
 * Reads the shared property context (provided by `PropertyLayout`) to present
 * the property by its human-readable **name** — never its raw UUID
 * (Requirements 2.1, 3.1). Renders a breadcrumb trail
 * `Properties > {property name} > {sub-page}` (Requirement 2.2) above the
 * heading, and the per-property sub-navigation as a labelled `nav` landmark so
 * screen-reader users can distinguish it from the primary navigation, with
 * `aria-current="page"` applied to the active link (Requirements 2.4, 14.1).
 */
export function PropertySection({
  propertyId: propertyIdProp,
  title,
  description,
}: PropertySectionProps) {
  const context = usePropertyContext();
  // Prefer the explicit prop for building paths, but fall back to the context
  // id so the component works whether or not a prop is supplied.
  const propertyId = propertyIdProp || context.propertyId;
  const propertyName = resolvePropertyName(
    context.status,
    context.property?.name,
  );

  const crumbs: Crumb[] = [
    { label: "Properties", to: "/properties" },
    { label: propertyName, to: `/properties/${propertyId}` },
    { label: title },
  ];

  return (
    <section aria-labelledby="page-heading">
      <Breadcrumb items={crumbs} />

      <h1 id="page-heading" className="mt-2 text-2xl font-semibold text-fg">
        {title}
      </h1>
      <p className="mt-1 text-sm text-fg-subtle">{propertyName}</p>

      <nav aria-label="Property sections" className="mt-4">
        <ul className="flex flex-wrap gap-2">
          {PROPERTY_NAV.map((item) => (
            <li key={item.segment}>
              <NavLink
                to={propertyPath(propertyId, item.segment)}
                className={({ isActive }) =>
                  [
                    "inline-block rounded-md px-3 py-1.5 text-sm font-medium",
                    "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                    isActive
                      ? "bg-accent text-accent-fg"
                      : "text-fg-muted hover:bg-surface-muted",
                  ].join(" ")
                }
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <p className="mt-6 text-fg-muted">{description}</p>
    </section>
  );
}
