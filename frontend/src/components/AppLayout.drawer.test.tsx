import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "../App";
import { ToastProvider } from "./ui";
import { ThemeProvider } from "../theme/ThemeProvider";

/**
 * Mobile drawer tests (task 29.2): icon controls with accessible names and
 * 44px mobile sizing, ARIA wiring, Escape focus return, and the focus rule
 * for choosing a destination (Req 18.8, 18.9, 5.3).
 */
function renderAt(path: string) {
  return render(
    <ThemeProvider><ToastProvider>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </ToastProvider></ThemeProvider>,
  );
}

const openName = /open navigation menu/i;

describe("AppLayout drawer — controls (Req 18.8)", () => {
  it("renders the open control as an icon button with a 44px mobile size", () => {
    renderAt("/");
    const open = screen.getByRole("button", { name: openName });
    expect(open.querySelector("svg")).not.toBeNull();
    expect(open.className).toContain("max-md:h-11");
    expect(open.className).toContain("max-md:w-11");
  });

  it("renders the close control as an icon button named 'Close menu'", async () => {
    const user = userEvent.setup();
    renderAt("/");
    await user.click(screen.getByRole("button", { name: openName }));
    const dialog = await screen.findByRole("dialog");
    const close = within(dialog).getByRole("button", { name: "Close menu" });
    expect(close.querySelector("svg")).not.toBeNull();
    expect(close.className).toContain("max-md:h-11");
    expect(close.className).toContain("max-md:w-11");
  });

  it("keeps aria-controls/aria-expanded on the open control", async () => {
    const user = userEvent.setup();
    renderAt("/");
    const open = screen.getByRole("button", { name: openName });
    expect(open).toHaveAttribute("aria-controls", "mobile-nav");
    expect(open).toHaveAttribute("aria-expanded", "false");
    await user.click(open);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("id", "mobile-nav");
    expect(open).toHaveAttribute("aria-expanded", "true");
  });

  it("closes with the close control", async () => {
    const user = userEvent.setup();
    renderAt("/");
    await user.click(screen.getByRole("button", { name: openName }));
    await user.click(await screen.findByRole("button", { name: "Close menu" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("AppLayout header — Search button (Req 1.4)", () => {
  it("renders a 44px-on-narrow Search button that opens the palette", async () => {
    const user = userEvent.setup();
    renderAt("/");
    const search = screen.getByRole("button", { name: "Search" });
    expect(search).toHaveAttribute("aria-keyshortcuts", "Control+K Meta+K");
    expect(search.className).toContain("max-md:h-11");
    expect(search.className).toContain("max-md:w-11");
    await user.click(search);
    expect(
      await screen.findByRole("dialog", { name: "Command palette" }),
    ).toBeInTheDocument();
  });
});

describe("AppLayout drawer — focus (Req 18.9, 5.3)", () => {
  it("returns focus to the menu button when closed with Escape", async () => {
    const user = userEvent.setup();
    renderAt("/");
    const open = screen.getByRole("button", { name: openName });
    await user.click(open);
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(open).toHaveFocus());
  });

  it("closes on choosing a destination and focuses the new page h1, not the menu button", async () => {
    const user = userEvent.setup();
    renderAt("/");
    const open = screen.getByRole("button", { name: openName });
    await user.click(open);
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("link", { name: /properties/i }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    const heading = await screen.findByRole("heading", { level: 1 });
    await waitFor(() => expect(heading).toHaveFocus());
    expect(open).not.toHaveFocus();
  });
});

describe("AppLayout drawer — contents (Req 18.x)", () => {
  it("lists the same groups as the desktop navigation", async () => {
    const user = userEvent.setup();
    renderAt("/");
    const labels = (root: HTMLElement) =>
      within(root)
        .getAllByRole("group")
        .map(
          (g) =>
            g.getAttribute("aria-label") ??
            document.getElementById(g.getAttribute("aria-labelledby")!)
              ?.textContent,
        );
    const desktop = labels(
      screen.getByRole("navigation", { name: /primary/i }),
    );
    await user.click(screen.getByRole("button", { name: openName }));
    expect(labels(await screen.findByRole("dialog"))).toEqual(desktop);
  });
});
