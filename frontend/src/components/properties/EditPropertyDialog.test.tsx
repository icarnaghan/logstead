import { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EditPropertyDialog } from "./EditPropertyDialog";
import { useOpenerFocusReturn } from "../ui";
import { ApiError, type Property } from "../../api/properties";

const property: Property = {
  id: "p1",
  user_id: "u1",
  name: "Maple Duplex",
  address_text: "1 Maple St, Springfield",
  property_type: "duplex",
};

function renderDialog(
  overrides: Partial<React.ComponentProps<typeof EditPropertyDialog>> = {},
) {
  const onUpdated = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <EditPropertyDialog
      property={property}
      open
      onOpenChange={onOpenChange}
      onUpdated={onUpdated}
      {...overrides}
    />,
  );
  return { onUpdated, onOpenChange };
}

describe("EditPropertyDialog", () => {
  it("prefills the form from the property", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByLabelText(/name/i)).toHaveValue("Maple Duplex");
    expect(within(dialog).getByLabelText(/address/i)).toHaveValue(
      "1 Maple St, Springfield",
    );
    expect(within(dialog).getByLabelText(/property type/i)).toHaveValue(
      "duplex",
    );
  });

  it("saves edits via update and notifies the parent", async () => {
    const user = userEvent.setup();
    const updated: Property = { ...property, name: "Maple Duplex (A)" };
    const update = vi.fn().mockResolvedValue(updated);
    const { onUpdated } = renderDialog({ update });

    const dialog = screen.getByRole("dialog");
    const name = within(dialog).getByLabelText(/name/i);
    await user.clear(name);
    await user.type(name, "Maple Duplex (A)");
    await user.click(
      within(dialog).getByRole("button", { name: /save changes/i }),
    );

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith("p1", {
        name: "Maple Duplex (A)",
        address_text: "1 Maple St, Springfield",
        property_type: "duplex",
      }),
    );
    expect(onUpdated).toHaveBeenCalledWith(updated);
  });

  it("validates required name and address before saving", async () => {
    const user = userEvent.setup();
    const update = vi.fn();
    renderDialog({ update });

    const dialog = screen.getByRole("dialog");
    await user.clear(within(dialog).getByLabelText(/name/i));
    await user.click(
      within(dialog).getByRole("button", { name: /save changes/i }),
    );

    // Shown in both the error summary and next to the field.
    expect(
      (await within(dialog).findAllByText(/name is required/i)).length,
    ).toBeGreaterThan(0);
    expect(update).not.toHaveBeenCalled();
  });

  it("surfaces a 400 field error on the offending input", async () => {
    const user = userEvent.setup();
    const update = vi
      .fn()
      .mockRejectedValue(
        new ApiError(400, "That name is already taken.", {
          field: "name",
          message: "That name is already taken.",
        }),
      );
    renderDialog({ update });

    const dialog = screen.getByRole("dialog");
    await user.click(
      within(dialog).getByRole("button", { name: /save changes/i }),
    );

    expect(
      (await within(dialog).findAllByText(/that name is already taken/i)).length,
    ).toBeGreaterThan(0);
  });

  describe("RecordModal behavior", () => {
    function Harness({
      update,
      onUpdated = vi.fn(),
    }: {
      update?: React.ComponentProps<typeof EditPropertyDialog>["update"];
      onUpdated?: (p: Property) => void;
    }) {
      const [open, setOpen] = useState(false);
      const { rememberOpener, handleCloseAutoFocus } = useOpenerFocusReturn();
      return (
        <>
          <button
            type="button"
            onClick={() => {
              rememberOpener();
              setOpen(true);
            }}
          >
            Open edit
          </button>
          <EditPropertyDialog
            property={property}
            open={open}
            onOpenChange={setOpen}
            onUpdated={onUpdated}
            onCloseAutoFocus={handleCloseAutoFocus}
            update={update}
          />
        </>
      );
    }

    async function openDialog(ui = <Harness />) {
      const user = userEvent.setup();
      render(ui);
      const opener = screen.getByRole("button", { name: "Open edit" });
      await user.click(opener);
      const dialog = await screen.findByRole("dialog", { name: "Edit property" });
      return { user, opener, dialog };
    }

    it("returns focus to the opener when closed", async () => {
      const { user, opener, dialog } = await openDialog();
      await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
      await waitFor(() =>
        expect(screen.queryByRole("dialog", { hidden: true })).toBeNull(),
      );
      await waitFor(() => expect(opener).toHaveFocus());
    });

    it("opens as a dialog with prefilled values", async () => {
      const { dialog } = await openDialog();
      expect(within(dialog).getByLabelText(/name/i)).toHaveValue("Maple Duplex");
      expect(within(dialog).getByLabelText(/address/i)).toHaveValue(
        "1 Maple St, Springfield",
      );
    });

    it("closes and refreshes the list after a successful save", async () => {
      const updated: Property = { ...property, name: "Renamed" };
      const update = vi.fn().mockResolvedValue(updated);
      const onUpdated = vi.fn();
      const { user, dialog } = await openDialog(
        <Harness update={update} onUpdated={onUpdated} />,
      );
      const name = within(dialog).getByLabelText(/name/i);
      await user.clear(name);
      await user.type(name, "Renamed");
      await user.click(
        within(dialog).getByRole("button", { name: /save changes/i }),
      );
      await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(updated));
      await waitFor(() =>
        expect(screen.queryByRole("dialog", { hidden: true })).toBeNull(),
      );
    });

    it("shows a failure inside the dialog and keeps the entered values", async () => {
      const update = vi
        .fn()
        .mockRejectedValue(new ApiError(500, "Server exploded.", null));
      const { user, dialog } = await openDialog(<Harness update={update} />);
      const name = within(dialog).getByLabelText(/name/i);
      await user.clear(name);
      await user.type(name, "Edited");
      await user.click(
        within(dialog).getByRole("button", { name: /save changes/i }),
      );
      expect(
        (await within(dialog).findAllByText(/server exploded/i)).length,
      ).toBeGreaterThan(0);
      expect(screen.getByRole("dialog", { name: "Edit property" })).toBe(dialog);
      expect(within(dialog).getByLabelText(/name/i)).toHaveValue("Edited");
    });

    it("prompts before closing when dirty, and Keep editing retains edits", async () => {
      const { user, dialog } = await openDialog();
      await user.type(within(dialog).getByLabelText(/name/i), " X");
      await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
      expect(
        await screen.findByRole("dialog", { name: "Discard changes?" }),
      ).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Keep editing" }));
      expect(within(dialog).getByLabelText(/name/i)).toHaveValue(
        "Maple Duplex X",
      );
    });

    it("Discard closes a dirty dialog", async () => {
      const { user, dialog } = await openDialog();
      await user.type(within(dialog).getByLabelText(/name/i), " X");
      await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
      await user.click(await screen.findByRole("button", { name: "Discard" }));
      await waitFor(() =>
        expect(screen.queryByRole("dialog", { hidden: true })).toBeNull(),
      );
    });

    it("closes without a prompt when edits are restored to the original", async () => {
      const { user, dialog } = await openDialog();
      const name = within(dialog).getByLabelText(/name/i);
      await user.type(name, "X");
      await user.type(name, "{Backspace}");
      await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
      expect(screen.queryByText("Discard changes?")).toBeNull();
      await waitFor(() =>
        expect(screen.queryByRole("dialog", { hidden: true })).toBeNull(),
      );
    });
  });
});
