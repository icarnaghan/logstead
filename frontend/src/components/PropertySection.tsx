import { NavLink } from "react-router-dom";
import { PROPERTY_NAV, propertyPath } from "./navConfig";

interface PropertySectionProps {
  /** The selected property's id, taken from the route params. */
  propertyId: string;
  /** Page heading for this sub-section. */
  title: string;
  /** Short descriptive text under the heading. */
  description: string;
}

/**
 * Shared layout for the per-property sub-sections (Transactions, Depreciable
 * Assets, Schedule E Report).
 *
 * Renders the per-property sub-navigation as a labelled `nav` landmark so
 * screen-reader users can distinguish it from the primary navigation, with
 * `aria-current="page"` applied to the active link (Requirement 14.1, 14.4).
 */
export function PropertySection({
  propertyId,
  title,
  description,
}: PropertySectionProps) {
  return (
    <section aria-labelledby="page-heading">
      <h1 id="page-heading" className="text-2xl font-semibold text-fg">
        {title}
      </h1>
      <p className="mt-1 text-sm text-fg-subtle">Property: {propertyId}</p>

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
