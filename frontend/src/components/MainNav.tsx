import { useId, type MouseEvent } from "react";
import { NavLink } from "react-router-dom";
import { useGuardedNavigate } from "../lib/navigationGuard";
import { NAV_GROUPS, type NavIconName } from "./navConfig";
import {
  BriefcaseIcon,
  BuildingIcon,
  CarryforwardIcon,
  DashboardIcon,
  HistoryIcon,
  ReportIcon,
  UploadIcon,
} from "./ui/icons";

interface MainNavProps {
  /**
   * Called once navigation proceeds (after the guard confirm, if any). Used by the mobile nav to close the
   * dialog once the user navigates.
   */
  onNavigate?: () => void;
}

const ICONS = {
  dashboard: DashboardIcon,
  properties: BuildingIcon,
  businesses: BriefcaseIcon,
  reports: ReportIcon,
  carryforward: CarryforwardIcon,
  import: UploadIcon,
  activity: HistoryIcon,
} satisfies Record<NavIconName, typeof DashboardIcon>;

/**
 * The grouped primary navigation (Requirement 18).
 *
 * Rendered inside a `nav` landmark by the shell (desktop sidebar) and inside
 * the mobile navigation dialog, so both show the same groups and items. Each
 * group is labelled; icons are decorative. `NavLink` sets `aria-current="page"`
 * on the active link, which is shown with a tinted background and an accent
 * bar rather than a solid accent block.
 */
export function MainNav({ onNavigate }: MainNavProps) {
  const baseId = useId();
  const { go } = useGuardedNavigate();
  // Plain primary clicks go through the navigation guard; modified and
  // non-primary clicks keep the browser default (Requirement 30.5).
  const handleClick = (event: MouseEvent<HTMLAnchorElement>, to: string) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    event.preventDefault();
    go(to, onNavigate);
  };
  return (
    <div className="space-y-4">
      {NAV_GROUPS.map((group) => {
        const labelId = `${baseId}-${group.id}`;
        return (
          <div key={group.id} role="group" aria-labelledby={labelId}>
            <p
              id={labelId}
              className="px-3 pb-1 text-caption uppercase tracking-wide text-fg-subtle"
            >
              {group.label}
            </p>
            <ul className="space-y-1" aria-labelledby={labelId}>
              {group.items.map((item) => {
                const Icon = item.icon ? ICONS[item.icon] : null;
                return (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      end={item.end}
                      onClick={(event) => handleClick(event, item.to)}
                      className={({ isActive }) =>
                        [
                          "relative flex items-center gap-3 rounded-md px-3 py-2 text-sm max-md:min-h-11",
                          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                          isActive
                            ? "bg-accent-subtle text-accent font-medium before:absolute before:inset-y-1.5 before:left-0 before:w-1 before:rounded-full before:bg-accent"
                            : "text-fg-muted font-medium hover:bg-surface-muted",
                        ].join(" ")
                      }
                    >
                      {Icon ? <Icon aria-hidden="true" /> : null}
                      {item.label}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
