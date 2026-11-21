/**
 * Hand-authored inline SVG icons (design D5, Requirement 18.3).
 *
 * All icons share a 24px grid, a 1.75 stroke, `currentColor`, and are
 * decorative: `aria-hidden="true"` and `focusable="false"`. Callers that need
 * an accessible name put it on the surrounding control, not the icon.
 */
import type { ReactNode, SVGProps } from "react";

export type IconProps = SVGProps<SVGSVGElement>;

function createIcon(displayName: string, children: ReactNode) {
  const Icon = ({ className = "h-5 w-5", ...rest }: IconProps) => (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
      {...rest}
    >
      {children}
    </svg>
  );
  Icon.displayName = displayName;
  return Icon;
}

export const DashboardIcon = createIcon(
  "DashboardIcon",
  <>
    <rect x="3.5" y="3.5" width="7" height="8" rx="1.5" />
    <rect x="13.5" y="3.5" width="7" height="5" rx="1.5" />
    <rect x="13.5" y="11.5" width="7" height="9" rx="1.5" />
    <rect x="3.5" y="14.5" width="7" height="6" rx="1.5" />
  </>,
);

export const BuildingIcon = createIcon(
  "BuildingIcon",
  <>
    <path d="M5 21V4.5A1.5 1.5 0 0 1 6.5 3h8A1.5 1.5 0 0 1 16 4.5V21" />
    <path d="M16 9h2.5A1.5 1.5 0 0 1 20 10.5V21" />
    <path d="M3 21h18" />
    <path d="M9 7h3M9 11h3M9 15h3" />
  </>,
);

export const BriefcaseIcon = createIcon(
  "BriefcaseIcon",
  <>
    <rect x="3" y="7" width="18" height="13" rx="2" />
    <path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7" />
    <path d="M3 13h18" />
  </>,
);

export const ReportIcon = createIcon(
  "ReportIcon",
  <>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5" />
    <path d="M9 17v-3M12 17v-5M15 17v-2" />
  </>,
);

export const CarryforwardIcon = createIcon(
  "CarryforwardIcon",
  <>
    <path d="M4 12h14" />
    <path d="m13 7 5 5-5 5" />
    <path d="M21 5v14" />
  </>,
);

export const UploadIcon = createIcon(
  "UploadIcon",
  <>
    <path d="M12 16V4" />
    <path d="m7 9 5-5 5 5" />
    <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
  </>,
);

export const HistoryIcon = createIcon(
  "HistoryIcon",
  <>
    <path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1" />
    <path d="M3.5 4v4.5H8" />
    <path d="M12 7.5V12l3 2" />
  </>,
);

export const MenuIcon = createIcon(
  "MenuIcon",
  <path d="M4 6h16M4 12h16M4 18h16" />,
);

export const XIcon = createIcon("XIcon", <path d="M6 6l12 12M18 6 6 18" />);

export const CheckIcon = createIcon("CheckIcon", <path d="m5 12.5 4.5 4.5L19 7.5" />);

export const ChevronUpIcon = createIcon("ChevronUpIcon", <path d="m6 15 6-6 6 6" />);

export const ChevronDownIcon = createIcon("ChevronDownIcon", <path d="m6 9 6 6 6-6" />);

export const SortIcon = createIcon(
  "SortIcon",
  <>
    <path d="m8 9 4-4 4 4" />
    <path d="m8 15 4 4 4-4" />
  </>,
);

export const AlertIcon = createIcon(
  "AlertIcon",
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7.5v5" />
    <path d="M12 16.5h.01" />
  </>,
);

export const SearchIcon = createIcon(
  "SearchIcon",
  <>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m20 20-4.2-4.2" />
  </>,
);

export const PlusIcon = createIcon("PlusIcon", <path d="M12 5v14M5 12h14" />);
