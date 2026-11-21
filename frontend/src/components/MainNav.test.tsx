import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { MainNav } from "./MainNav";
import { NAV_GROUPS } from "./navConfig";
import { NavigationGuardProvider, useRegisterDirty } from "../lib/navigationGuard";

/**
 * Grouped primary navigation (Requirements 18.1-18.5).
 */
function renderNav(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <nav aria-label="Primary">
        <MainNav />
      </nav>
    </MemoryRouter>,
  );
}

describe("MainNav — groups (Req 18.1, 18.2)", () => {
  it("renders three labelled groups with the right links in order", () => {
    renderNav();
    const groups = screen.getAllByRole("group");
    expect(groups).toHaveLength(3);
    NAV_GROUPS.forEach((group, i) => {
      const el = groups[i];
      expect(el).toHaveAccessibleName(group.label);
      const labelId = el.getAttribute("aria-labelledby");
      expect(labelId).toBeTruthy();
      expect(document.getElementById(labelId!)).toHaveTextContent(group.label);
      const links = within(el).getAllByRole("link");
      expect(links.map((l) => l.textContent)).toEqual(
        group.items.map((item) => item.label),
      );
      expect(within(el).getByRole("list")).toHaveAccessibleName(group.label);
    });
  });

  it("marks icons aria-hidden", () => {
    renderNav();
    for (const link of screen.getAllByRole("link")) {
      const svg = link.querySelector("svg");
      expect(svg).not.toBeNull();
      expect(svg).toHaveAttribute("aria-hidden", "true");
    }
  });
});

describe("MainNav — active state (Req 18.3, 18.4)", () => {
  it("sets aria-current and active styling on the active link only", () => {
    renderNav("/carryforward");
    const links = screen.getAllByRole("link");
    const current = links.filter(
      (l) => l.getAttribute("aria-current") === "page",
    );
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("Carryforward");
    expect(current[0].className).toContain("bg-accent-subtle");
    expect(current[0].className).toContain("text-accent");
    expect(current[0].className).toContain("font-medium");
    expect(current[0].className).not.toMatch(/(^|\s)bg-accent(\s|$)/);
    for (const l of links.filter((x) => x !== current[0])) {
      expect(l.className).not.toContain("bg-accent-subtle");
    }
  });

  it("does not mark Dashboard active on nested routes", () => {
    renderNav("/properties");
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute(
      "aria-current",
    );
  });
});

describe("MainNav — accessibility (Req 18.5)", () => {
  it("has no detectable axe violations", async () => {
    const { container } = renderNav("/reports");
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});

function Dirty({ dirty }: { dirty: boolean }) {
  useRegisterDirty("test", dirty);
  return null;
}
function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}
function renderGuarded(dirty: boolean, onNavigate = vi.fn()) {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <NavigationGuardProvider>
        <Dirty dirty={dirty} />
        <nav aria-label="Primary">
          <MainNav onNavigate={onNavigate} />
        </nav>
        <Where />
      </NavigationGuardProvider>
    </MemoryRouter>,
  );
  return onNavigate;
}
describe("MainNav — navigation guard (Req 30)", () => {
  it("dirty: asks first; Keep editing stays and leaves the drawer open", async () => {
    const user = userEvent.setup();
    const onNavigate = renderGuarded(true);
    await user.click(screen.getByRole("link", { name: "Properties" }));
    expect(await screen.findByText("Discard changes?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/);
    expect(onNavigate).not.toHaveBeenCalled();
  });
  it("dirty: Discard navigates and then calls onNavigate", async () => {
    const user = userEvent.setup();
    const onNavigate = renderGuarded(true);
    await user.click(screen.getByRole("link", { name: "Properties" }));
    await user.click(await screen.findByRole("button", { name: "Discard" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/properties");
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });
  it("clean: navigates directly with no confirm", async () => {
    const user = userEvent.setup();
    const onNavigate = renderGuarded(false);
    await user.click(screen.getByRole("link", { name: "Properties" }));
    expect(screen.queryByText("Discard changes?")).not.toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/properties");
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });
  it("modifier and middle clicks keep the browser default and show no confirm", () => {
    const onNavigate = renderGuarded(true);
    const link = screen.getByRole("link", { name: "Properties" });
    expect(link).toHaveAttribute("href", "/properties");
    expect(fireEvent.click(link, { ctrlKey: true })).toBe(true);
    expect(fireEvent.click(link, { metaKey: true })).toBe(true);
    expect(fireEvent.click(link, { button: 1 })).toBe(true);
    expect(screen.queryByText("Discard changes?")).not.toBeInTheDocument();
    expect(onNavigate).not.toHaveBeenCalled();
  });
});
