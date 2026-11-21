import { useContext, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { ImportsDirtyContext } from "../lib/importsDirty";
import { ConfirmDialog } from "./ui";
import { IMPORT_NAV } from "./navConfig";
import { sectionTabClassName } from "./sectionTabStyles";

/**
 * Route-based Section Tabs for the Imports section.
 *
 * Renders `nav[aria-label="Import methods"]` from `IMPORT_NAV`. `end` is
 * plumbed through so the "Enter manually" tab is not active on the PDF route.
 * `NavLink` applies `aria-current="page"` to the active tab only. Styling is
 * shared with `PropertySectionTabs` via `sectionTabClassName`.
 *
 * When the active form is dirty, switching to a different tab asks for
 * discard confirmation first.
 */
export function ImportSectionTabs() {
  const { dirty, setDirty } = useContext(ImportsDirtyContext);
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [pendingTo, setPendingTo] = useState<string | null>(null);

  return (
    <nav aria-label="Import methods" className="mt-4">
      <ul className="flex flex-wrap gap-2">
        {IMPORT_NAV.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.end}
              className={({ isActive }) => sectionTabClassName(isActive)}
              onClick={(event) => {
                if (dirty && item.to !== pathname) {
                  event.preventDefault();
                  setPendingTo(item.to);
                }
              }}
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
      <ConfirmDialog
        open={pendingTo !== null}
        onOpenChange={(open) => {
          if (!open) setPendingTo(null);
        }}
        title="Discard changes?"
        description="You have unsaved changes. Switching tabs will discard them."
        confirmLabel="Discard"
        cancelLabel="Keep editing"
        onConfirm={() => {
          const to = pendingTo;
          setPendingTo(null);
          setDirty(false);
          if (to) navigate(to);
        }}
      />
    </nav>
  );
}
