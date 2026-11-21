import { render } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import * as icons from "./icons";

/**
 * Tests for the shared icon set (task 27.2, Requirement 18.3).
 */

const iconEntries = Object.entries(icons).filter(
  ([name]) => name.endsWith("Icon"),
) as [string, (props: icons.IconProps) => React.JSX.Element][];

describe("icons (Req 18.3)", () => {
  it("exports the full icon set", () => {
    expect(iconEntries.map(([n]) => n).sort()).toEqual(
      [
        "DashboardIcon", "BuildingIcon", "BriefcaseIcon", "ReportIcon", "HistoryIcon",
        "CarryforwardIcon", "UploadIcon", "MenuIcon", "XIcon", "CheckIcon",
        "ChevronUpIcon", "ChevronDownIcon", "SortIcon", "AlertIcon",
        "SearchIcon", "PlusIcon",
      ].sort(),
    );
  });

  describe.each(iconEntries)("%s", (_name, Icon) => {
    it("renders a decorative svg on the shared 24px base", () => {
      const { container } = render(<Icon />);
      const svg = container.querySelector("svg");
      expect(svg).not.toBeNull();
      expect(svg).toHaveAttribute("aria-hidden", "true");
      expect(svg).toHaveAttribute("focusable", "false");
      expect(svg).toHaveAttribute("viewBox", "0 0 24 24");
      expect(svg).toHaveAttribute("stroke", "currentColor");
    });

    it("accepts a className override", () => {
      const { container } = render(<Icon className="h-4 w-4 test-x" />);
      const svg = container.querySelector("svg");
      expect(svg).toHaveClass("h-4", "w-4", "test-x");
      expect(svg).not.toHaveClass("h-5");
    });
  });

  it("has no axe violations in a nav with icon and label", async () => {
    const { container } = render(
      <nav aria-label="Main">
        <a href="/dashboard">
          <icons.DashboardIcon />
          <span>Dashboard</span>
        </a>
      </nav>,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
