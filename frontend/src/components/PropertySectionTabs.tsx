import { useId, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { currentSection } from "../lib/propertySections";
import { PROPERTY_NAV, propertyPath } from "./navConfig";
import { sectionTabClassName } from "./sectionTabStyles";

interface PropertySectionTabsProps {
  /** Property id used to build each tab's path. */
  propertyId: string;
}

/**
 * Shared, presentational per-property Section Tabs.
 *
 * Renders the `nav[aria-label="Property sections"]` landmark built from
 * `PROPERTY_NAV`, mapping each entry to a `NavLink` whose target is
 * `propertyPath(propertyId, item.segment)`. The `end={item.end}` flag plumbs
 * React Router's exact matching so the Overview (index) tab is not marked
 * active on sub-routes. The active `NavLink` applies `aria-current="page"`.
 *
 * Below the `md` breakpoint the list sits behind a disclosure button labeled
 * "Property sections: {current}" (WAI-ARIA disclosure navigation pattern). At
 * `md` and wider the button is hidden and the links show as a wrapping row.
 * One landmark and one list exist at every width.
 *
 * Shared by `PropertySection` (sub-pages) and the property overview so both
 * render identical tabs from the same source.
 */
export function PropertySectionTabs({ propertyId }: PropertySectionTabsProps) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const { pathname } = useLocation();
  const current = currentSection(pathname, propertyId);

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape" && open) {
      setOpen(false);
      buttonRef.current?.focus();
    }
  }

  function handleBlur(event: FocusEvent<HTMLElement>) {
    const next = event.relatedTarget;
    if (open && next instanceof Node && !event.currentTarget.contains(next)) {
      setOpen(false);
    }
  }

  return (
    // The handlers only observe Escape and focus leaving bubbling up from the
    // focusable button and links inside; the nav itself is not interactive.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <nav
      aria-label="Property sections"
      className="mt-4"
      onKeyDown={handleKeyDown}
      onBlur={handleBlur}
    >
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex min-h-11 w-full items-center justify-between rounded-md border border-border px-3 py-1.5 text-left text-sm font-medium text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent md:hidden"
      >
        <span>Property sections: {current?.label ?? "Overview"}</span>
        <span aria-hidden="true">{open ? "▴" : "▾"}</span>
      </button>
      <ul
        id={listId}
        className={
          open
            ? "mt-2 flex flex-col gap-1 md:mt-0 md:flex-row md:flex-wrap md:gap-2"
            : "hidden md:flex md:flex-wrap md:gap-2"
        }
      >
        {PROPERTY_NAV.map((item) => (
          <li key={item.segment}>
            <NavLink
              to={propertyPath(propertyId, item.segment)}
              end={item.end}
              onClick={() => setOpen(false)}
              className={({ isActive }) => sectionTabClassName(isActive)}
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
