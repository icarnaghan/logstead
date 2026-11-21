import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import * as Dialog from "@radix-ui/react-dialog";
import { useRef } from "react";

import { RecordModal } from "./index";
import { useRecordModal } from "./useRecordModal";

// Radix registers its outside-interaction listeners on a timer.
const tick = () => new Promise((r) => setTimeout(r, 10));

function setup(props: Partial<Parameters<typeof RecordModal>[0]> = {}) {
  const onOpenChange = vi.fn();
  const utils = render(
    <div>
      <button type="button">Background action</button>
      <div role="region" aria-label="Notifications (F8)">
        <button type="button">Toast action</button>
      </div>
      <RecordModal
        open
        onOpenChange={onOpenChange}
        title="Add loan"
        description="Enter the loan terms."
        {...props}
      >
        <label>
          Name
          <input type="text" />
        </label>
        <button type="button">Save</button>
      </RecordModal>
    </div>,
  );
  return { onOpenChange, ...utils };
}

describe("RecordModal", () => {
  it("is exported from components/ui", () => {
    expect(RecordModal).toBeTypeOf("function");
  });

  it("renders a dialog with accessible name and description", () => {
    setup();
    const dialog = screen.getByRole("dialog", { name: "Add loan" });
    expect(dialog).toHaveAccessibleDescription("Enter the loan terms.");
  });

  it("moves focus inside on open and keeps Tab inside", async () => {
    const user = userEvent.setup();
    setup();
    const dialog = screen.getByRole("dialog");
    expect(dialog.contains(document.activeElement)).toBe(true);
    for (let i = 0; i < 6; i++) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });

  it("hides the background from role queries", () => {
    setup();
    expect(
      screen.queryByRole("button", { name: "Background action" }),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
  });

  it("closes on Escape and outside click when dismissible", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = setup();
    await user.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);

    onOpenChange.mockClear();
    await tick();
    fireEvent.pointerDown(document.body);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("ignores Escape and outside click when not dismissible", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = setup({ dismissible: false });
    await user.keyboard("{Escape}");
    await tick();
    fireEvent.pointerDown(document.body);
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("does not close when clicking inside the toast viewport", async () => {
    const { onOpenChange } = setup();
    const toast = document.querySelector<HTMLElement>(
      '[role="region"][aria-label^="Notifications"] button',
    )!;
    await tick();
    fireEvent.pointerDown(toast);
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("scrolls internally on short viewports", () => {
    setup();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveClass("max-h-[90dvh]", "p-4", "sm:p-6");
    expect(dialog).toHaveClass("w-[calc(100vw-1.5rem)]", "sm:w-[92vw]");
    expect(dialog).toHaveClass("overflow-y-auto");
  });
  it("renders no footer bar without the footer slot", () => {
    setup();
    expect(screen.queryByTestId("record-modal-footer")).toBeNull();
  });
  it("renders the footer slot in a sticky bottom bar inside the dialog", () => {
    setup({ footer: <button type="button">Footer save</button> });
    const bar = screen.getByTestId("record-modal-footer");
    expect(bar).toHaveClass("sticky", "bottom-0");
    expect(screen.getByRole("dialog")).toContainElement(bar);
    expect(bar).toContainElement(
      screen.getByRole("button", { name: "Footer save" }),
    );
  });

  it("has no axe violations", async () => {
    setup();
    const results = await axe(screen.getByRole("dialog"), {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });

  describe("discard confirmation", () => {
    const discardProps = () => ({
      open: true,
      onConfirm: vi.fn(),
      onCancel: vi.fn(),
    });

    it("renders no confirmation when the discard prop is absent", () => {
      setup();
      expect(screen.queryByText("Discard changes?")).toBeNull();
    });

    // Open the confirmation after mount, as happens in real use.
    function setupOpened(discard: ReturnType<typeof discardProps>) {
      const closed = { ...discard, open: false };
      const ui = (d: typeof discard) => (
        <RecordModal
          open
          onOpenChange={vi.fn()}
          title="Add loan"
          description="Enter the loan terms."
          discard={d}
        >
          <button type="button">Save</button>
        </RecordModal>
      );
      const utils = render(ui(closed));
      utils.rerender(ui(discard));
    }

    it("renders the stacked confirmation with the specified copy", () => {
      setupOpened(discardProps());
      const confirm = screen.getByRole("dialog", { name: "Discard changes?" });
      expect(confirm).toHaveAccessibleDescription(
        "You have unsaved changes. If you leave now they will be lost.",
      );
      expect(
        screen.getByRole("button", { name: "Keep editing" }),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Discard" })).toBeInTheDocument();
    });

    it("wires Discard and Keep editing to the guard", async () => {
      const user = userEvent.setup();
      const discard = discardProps();
      setupOpened(discard);
      await user.click(screen.getByRole("button", { name: "Keep editing" }));
      expect(discard.onCancel).toHaveBeenCalledTimes(1);
      await user.click(screen.getByRole("button", { name: "Discard" }));
      expect(discard.onConfirm).toHaveBeenCalledTimes(1);
    });

    it("stays closed when discard.open is false", () => {
      setup({ discard: { ...discardProps(), open: false } });
      expect(screen.queryByText("Discard changes?")).toBeNull();
    });

    it("non-dismissible still blocks Escape and outside click", async () => {
      const user = userEvent.setup();
      const { onOpenChange } = setup({
        dismissible: false,
        discard: { ...discardProps(), open: false },
      });
      await user.keyboard("{Escape}");
      await tick();
      fireEvent.pointerDown(document.body);
      expect(onOpenChange).not.toHaveBeenCalled();
    });

    it("toast clicks still do not close the modal with the confirmation present", async () => {
      const { onOpenChange } = setup({
        discard: { ...discardProps(), open: false },
      });
      const toast = document.querySelector<HTMLElement>(
        '[role="region"][aria-label^="Notifications"] button',
      )!;
      await tick();
      fireEvent.pointerDown(toast);
      expect(onOpenChange).not.toHaveBeenCalled();
    });
  });
});

describe("RecordModal discard flow (integrated with useRecordModal)", () => {
  function Harness() {
    const headingRef = useRef<HTMLHeadingElement>(null);
    const modal = useRecordModal<{ id: string }>([], {
      fallbackFocusRef: headingRef,
    });
    return (
      <div>
        <h1 ref={headingRef} tabIndex={-1}>
          Loans
        </h1>
        <button type="button" onClick={modal.openAdd}>
          Open add
        </button>
        <div role="region" aria-label="Notifications (F8)">
          <button type="button">Toast action</button>
        </div>
        <RecordModal
          open={modal.open}
          onOpenChange={(next) => {
            if (!next) modal.requestClose();
          }}
          title="Add loan"
          description="Enter the loan terms."
          discard={modal.discard}
          onCloseAutoFocus={modal.handleCloseAutoFocus}
        >
          <label>
            Name
            <input
              type="text"
              onChange={(e) => modal.setDirty(e.target.value !== "")}
            />
          </label>
          <button type="button" onClick={modal.requestClose}>
            Cancel
          </button>
          <button type="button" onClick={modal.close}>
            Save
          </button>
          <Dialog.Close aria-label="Close dialog">×</Dialog.Close>
        </RecordModal>
      </div>
    );
  }

  async function openDirty() {
    const user = userEvent.setup();
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Open add" });
    await user.click(trigger);
    await user.type(screen.getByLabelText("Name"), "abc");
    await tick();
    return { user, trigger };
  }

  const closePaths: Array<[string, (user: ReturnType<typeof userEvent.setup>) => Promise<void>]> = [
    ["Escape", async (user) => void (await user.keyboard("{Escape}"))],
    ["backdrop click", async () => void fireEvent.pointerDown(document.body)],
    [
      "close icon",
      async (user) =>
        void (await user.click(screen.getByRole("button", { name: "Close dialog" }))),
    ],
    [
      "Cancel button",
      async (user) =>
        void (await user.click(screen.getByRole("button", { name: "Cancel" }))),
    ],
  ];

  it.each(closePaths)(
    "%s with a dirty form shows the confirmation and keeps the modal open",
    async (_name, act) => {
      const { user } = await openDirty();
      await act(user);
      expect(
        await screen.findByRole("dialog", { name: "Discard changes?" }),
      ).toBeInTheDocument();
      expect(screen.getByText("Add loan")).toBeInTheDocument();
      expect(screen.getByLabelText("Name", { selector: "input" })).toHaveValue("abc");
    },
  );

  it("Discard closes the confirmation and the modal", async () => {
    const { user } = await openDirty();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(await screen.findByRole("button", { name: "Discard" }));
    expect(screen.queryByRole("dialog", { hidden: true })).toBeNull();
  });

  it("Keep editing retains edits and returns focus into the modal", async () => {
    const { user } = await openDirty();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(await screen.findByRole("button", { name: "Keep editing" }));
    expect(screen.queryByRole("dialog", { name: "Discard changes?" })).toBeNull();
    await tick(); // Radix restores focus on a timer
    const modal = screen.getByRole("dialog", { name: "Add loan" });
    expect(screen.getByLabelText("Name")).toHaveValue("abc");
    expect(modal.contains(document.activeElement)).toBe(true);
  });

  it("a clean close shows no confirmation", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Open add" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText("Discard changes?")).toBeNull();
    expect(screen.queryByRole("dialog", { hidden: true })).toBeNull();
  });

  it("a successful save closes without confirmation and returns focus to the trigger", async () => {
    const { user, trigger } = await openDirty();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.queryByText("Discard changes?")).toBeNull();
    expect(screen.queryByRole("dialog", { hidden: true })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("toast-viewport clicks do not close a dirty modal or open the confirmation", async () => {
    await openDirty();
    fireEvent.pointerDown(
      document.querySelector<HTMLElement>(
        '[role="region"][aria-label^="Notifications"] button',
      )!,
    );
    expect(screen.queryByText("Discard changes?")).toBeNull();
    expect(screen.getByRole("dialog", { name: "Add loan" })).toBeInTheDocument();
  });

  it("toast-viewport clicks leave the modal open while the confirmation is showing", async () => {
    const { user } = await openDirty();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await screen.findByRole("dialog", { name: "Discard changes?" });
    await tick();
    fireEvent.pointerDown(
      document.querySelector<HTMLElement>(
        '[role="region"][aria-label^="Notifications"] button',
      )!,
    );
    expect(screen.getByText("Add loan")).toBeInTheDocument();
    expect(screen.getByLabelText("Name", { selector: "input" })).toHaveValue("abc");
  });
});
