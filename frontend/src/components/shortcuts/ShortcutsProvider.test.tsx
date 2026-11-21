import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SHORTCUTS } from "../../lib/shortcuts/registry";
import { usePalette } from "../palette/paletteContext";
import { RecordModal } from "../ui/RecordModal";
import { ShortcutsProvider } from "./ShortcutsProvider";

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

function FakePalette({ opened }: { opened: (initial?: string) => void }) {
  const { registerPalette } = usePalette();
  useEffect(() => {
    let open = false;
    return registerPalette({
      open: (initial) => {
        open = true;
        opened(initial);
      },
      close: () => {
        open = false;
        opened("closed");
      },
      isOpen: () => open,
    });
  }, [registerPalette, opened]);
  return null;
}

function setup(extra?: React.ReactNode) {
  const opened = vi.fn();
  render(
    <MemoryRouter initialEntries={["/start"]}>
      <ShortcutsProvider>
        <FakePalette opened={opened} />
        <Where />
        <input aria-label="field" />
        <button type="button">btn</button>
        {extra}
      </ShortcutsProvider>
    </MemoryRouter>,
  );
  return { opened };
}

afterEach(() => vi.restoreAllMocks());

describe("ShortcutsProvider", () => {
  it("adds one document keydown listener and removes it on unmount", () => {
    const add = vi.spyOn(document, "addEventListener");
    const remove = vi.spyOn(document, "removeEventListener");
    const { unmount } = render(
      <MemoryRouter>
        <ShortcutsProvider>
          <span />
        </ShortcutsProvider>
      </MemoryRouter>,
    );
    const added = add.mock.calls.filter((c) => c[0] === "keydown");
    expect(added).toHaveLength(1);
    unmount();
    const removed = remove.mock.calls.filter((c) => c[0] === "keydown");
    expect(removed).toHaveLength(1);
    expect(removed[0][1]).toBe(added[0][1]);
  });

  it("opens the palette with `/` and the help dialog with `?`", async () => {
    const user = userEvent.setup();
    const { opened } = setup();
    await user.keyboard("/");
    expect(opened).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.keyboard("?");
    expect(
      await screen.findByRole("dialog", { name: "Keyboard shortcuts" }),
    ).toBeInTheDocument();
  });

  it("toggles the palette with Ctrl+K even from an input", async () => {
    const user = userEvent.setup();
    const { opened } = setup();
    await user.click(screen.getByLabelText("field"));
    await user.keyboard("{Control>}k{/Control}");
    expect(opened).toHaveBeenLastCalledWith(undefined);
    await user.keyboard("{Control>}k{/Control}");
    expect(opened).toHaveBeenLastCalledWith("closed");
  });

  it("ignores plain keys typed in an input", async () => {
    const user = userEvent.setup();
    const { opened } = setup();
    await user.click(screen.getByLabelText("field"));
    await user.keyboard("/?gd");
    expect(opened).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByTestId("where")).toHaveTextContent("/start");
  });

  it("ignores shortcuts while a RecordModal is open", async () => {
    const user = userEvent.setup();
    const { opened } = setup(
      <RecordModal open onOpenChange={() => {}} title="Add" description="d">
        <p>body</p>
      </RecordModal>,
    );
    await screen.findByRole("dialog", { name: "Add" });
    await user.keyboard("/?gd{Control>}k{/Control}");
    expect(opened).not.toHaveBeenCalled();
    expect(screen.getByTestId("where")).toHaveTextContent("/start");
    expect(
      screen.queryByRole("dialog", { name: "Keyboard shortcuts" }),
    ).toBeNull();
  });

  it("navigates on `g` then `d`", async () => {
    const user = userEvent.setup();
    setup();
    await user.keyboard("gd");
    expect(screen.getByTestId("where").textContent).toBe("/");
  });

  it("navigates to Activity on `g` then `a`", async () => {
    const user = userEvent.setup();
    setup();
    await user.keyboard("ga");
    expect(screen.getByTestId("where").textContent).toBe("/activity");
  });
  it("resets a pending sequence after the timeout", async () => {
    const user = userEvent.setup();
    setup();
    let now = 1_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    await user.keyboard("g");
    now += 1500;
    await user.keyboard("p");
    expect(screen.getByTestId("where")).toHaveTextContent("/start");
    await user.keyboard("g");
    now += 100;
    await user.keyboard("p");
    expect(screen.getByTestId("where").textContent).toBe("/properties");
  });

  it("lists every shortcut in the help dialog and closes it with Escape, returning focus", async () => {
    const user = userEvent.setup();
    setup();
    const opener = screen.getByRole("button", { name: "btn" });
    opener.focus();
    await user.keyboard("?");
    const dialog = await screen.findByRole("dialog", {
      name: "Keyboard shortcuts",
    });
    for (const def of SHORTCUTS) {
      expect(dialog).toHaveTextContent(def.label);
    }
    expect(dialog.querySelectorAll("dl")).toHaveLength(2);
    expect(dialog.querySelectorAll("kbd").length).toBeGreaterThanOrEqual(
      SHORTCUTS.length,
    );
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });
});
