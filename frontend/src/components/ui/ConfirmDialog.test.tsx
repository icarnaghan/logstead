import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";

/**
 * Unit + axe tests for the shared ConfirmDialog primitive
 * (task 3.6, Requirements 4.1, 4.2, 4.3).
 */

function renderDialog(
  props: Partial<React.ComponentProps<typeof ConfirmDialog>> = {},
) {
  const onConfirm = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <ConfirmDialog
      open
      onOpenChange={onOpenChange}
      title="Delete property"
      description="Delete 123 Main St? This cannot be undone."
      onConfirm={onConfirm}
      {...props}
    />,
  );
  return { onConfirm, onOpenChange };
}

describe("ConfirmDialog — confirm (Req 4.2)", () => {
  it("calls onConfirm when the confirm button is clicked", async () => {
    const { onConfirm } = renderDialog();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});

describe("ConfirmDialog — cancel (Req 4.3)", () => {
  it("does not call onConfirm and requests close when cancel is clicked", async () => {
    const { onConfirm, onOpenChange } = renderDialog();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe("ConfirmDialog — Esc dismissal (Req 4.3)", () => {
  it("does not call onConfirm and requests close on Escape", async () => {
    const { onConfirm, onOpenChange } = renderDialog();
    await userEvent.keyboard("{Escape}");
    expect(onConfirm).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe("ConfirmDialog — pending state", () => {
  it("disables the confirm button while pending", () => {
    renderDialog({ pending: true });
    expect(screen.getByRole("button", { name: /Delete/ })).toBeDisabled();
  });

  it("uses custom labels and the primary variant when not destructive", () => {
    renderDialog({
      confirmLabel: "Remove",
      cancelLabel: "Keep",
      destructive: false,
    });
    const confirm = screen.getByRole("button", { name: "Remove" });
    expect(screen.getByRole("button", { name: "Keep" })).toBeInTheDocument();
    expect(confirm).toHaveClass("bg-accent");
  });
});

describe("ConfirmDialog — accessibility", () => {
  it("has no axe violations when open", async () => {
    const { baseElement } = render(
      <ConfirmDialog
        open
        onOpenChange={() => {}}
        title="Delete property"
        description="Delete 123 Main St? This cannot be undone."
        onConfirm={() => {}}
      />,
    );
    const results = await axe(baseElement, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
