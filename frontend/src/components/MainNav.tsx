import { NavLink } from "react-router-dom";
import { PRIMARY_NAV } from "./navConfig";

interface MainNavProps {
  /**
   * Called when a link is activated. Used by the mobile nav to close the
   * dialog once the user navigates.
   */
  onNavigate?: () => void;
}

/**
 * The primary navigation link list.
 *
 * Rendered inside a `nav` landmark by the shell (desktop sidebar) and inside
 * the mobile navigation dialog. `NavLink` from react-router applies
 * `aria-current="page"` to the active link automatically, and the
 * `focus-visible` styles keep the links keyboard-navigable (Requirement 14.1,
 * 14.4).
 */
export function MainNav({ onNavigate }: MainNavProps) {
  return (
    <ul className="space-y-1">
      {PRIMARY_NAV.map((item) => (
        <li key={item.to}>
          <NavLink
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              [
                "block rounded-md px-3 py-2 text-sm font-medium",
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
  );
}
