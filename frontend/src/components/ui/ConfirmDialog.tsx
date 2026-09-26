import * as Dialog from "@radix-ui/react-dialog";
import { cn } from "../../lib/cn";
import { Button } from "./Button";

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** Description naming the record to be deleted (Requirement 4.1). */
  description: React.ReactNode;
  confirmLabel?: string; // default "Delete"
  cancelLabel?: string; // default "Cancel"
  /** When true (default) the confirm button uses the danger variant. */
  destructive?: boolean;
  onConfirm: () => void | Promise<void>;
  /** Disables confirm + shows a pending label while a delete is in flight. */
  pending?: boolean;
}

/**
 * Shared confirmation modal wrapping `@radix-ui/react-dialog`
 * (Requirements 1.4, 4.1, 4.5, 8.3, 8.5). Radix supplies the focus trap,
 * `Esc`-to-close, and focus-return for free. The backdrop derives from the
 * semantic `fg` token and the panel reuses the shared card elevation
 * (`shadow-card`) instead of the one-off `bg-slate-900/40` + `shadow-xl`
 * treatment it replaces (Requirement 8.3). Confirm is a danger `Button` and
 * cancel is a secondary `Button`, giving the single consistent Cancel/Delete
 * pairing required by Requirement 8.5.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Delete",
  cancelLabel = "Cancel",
  destructive = true,
  onConfirm,
  pending = false,
}: ConfirmDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-fg/40" />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 w-[90vw] max-w-md -translate-x-1/2 -translate-y-1/2",
            "rounded-lg border border-border bg-surface p-6 shadow-card focus:outline-none",
          )}
        >
          <Dialog.Title className="text-lg font-semibold text-fg">
            {title}
          </Dialog.Title>
          <Dialog.Description className="mt-2 text-sm text-fg-muted">
            {description}
          </Dialog.Description>
          <div className="mt-6 flex justify-end gap-3">
            <Button
              variant="secondary"
              onClick={() => onOpenChange(false)}
            >
              {cancelLabel}
            </Button>
            <Button
              variant={destructive ? "danger" : "primary"}
              onClick={() => onConfirm()}
              disabled={pending}
            >
              {pending ? `${confirmLabel}…` : confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
