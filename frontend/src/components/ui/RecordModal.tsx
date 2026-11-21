import { useLayoutEffect, useRef } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { cn } from "../../lib/cn";
import { ConfirmDialog } from "./ConfirmDialog";
import type { DiscardGuard } from "./useDiscardGuard";

export interface RecordModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Accessible name, e.g. "Add loan" or "Edit asset". */
  title: string;
  /** Accessible description shown under the title. */
  description: React.ReactNode;
  /** The form. Rendered only while open. */
  children: React.ReactNode;
  /**
   * When false, Escape and outside interaction are ignored (used while a save
   * is in flight). Default true.
   */
  dismissible?: boolean;
  /** Forwarded to Radix `Dialog.Content`; used for focus return. */
  onCloseAutoFocus?: (event: Event) => void;
  /**
   * Discard-changes confirmation state from `useRecordModal().discard`.
   * Renders a stacked confirmation dialog (Requirements 10.2-10.5).
   */
  discard?: DiscardGuard["discard"];
  /**
   * Optional action bar (e.g. Cancel and Save) pinned to the bottom of the
   * scrolling panel so it stays visible on short viewports.
   */
  footer?: React.ReactNode;
}

const TOAST_VIEWPORT_SELECTOR = '[role="region"][aria-label^="Notifications"]';

/**
 * Shared modal for add/edit record forms, wrapping `@radix-ui/react-dialog`.
 * Radix supplies the dialog role, focus trap, initial focus, and background
 * `aria-hidden`. Overlay and panel reuse the `ConfirmDialog` tokens; the
 * panel scrolls internally on short viewports (`max-h-[90dvh]`).
 *
 * Clicks inside the toast viewport never dismiss the modal, so a "Could not
 * save" toast cannot discard the user's entries.
 */
export function RecordModal({
  open,
  onOpenChange,
  title,
  description,
  children,
  dismissible = true,
  onCloseAutoFocus,
  discard,
  footer,
}: RecordModalProps) {
  // The confirmation has no trigger element, so Radix cannot restore focus
  // after "Keep editing". Remember what had focus when it opened (Req 10.4).
  const discardOpen = discard?.open ?? false;
  const returnFocusRef = useRef<Element | null>(null);
  useLayoutEffect(() => {
    if (discardOpen) returnFocusRef.current = document.activeElement;
  }, [discardOpen]);

  return (
    <>
      <Dialog.Root open={open} onOpenChange={onOpenChange}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-fg/40" />
          <Dialog.Content
            className={cn(
              "fixed left-1/2 top-1/2 z-50 max-h-[90dvh] w-[calc(100vw-1.5rem)] max-w-lg sm:w-[92vw] -translate-x-1/2 -translate-y-1/2 overflow-y-auto",
              "rounded-lg border border-border bg-surface p-4 shadow-card focus:outline-none sm:p-6",
            )}
            onEscapeKeyDown={(event) => {
              if (!dismissible) event.preventDefault();
            }}
            onInteractOutside={(event) => {
              const target = event.target;
              if (
                !dismissible ||
                discard?.open ||
                (target instanceof Element &&
                  target.closest(TOAST_VIEWPORT_SELECTOR))
              ) {
                event.preventDefault();
              }
            }}
            onCloseAutoFocus={onCloseAutoFocus}
          >
            <Dialog.Title className="text-lg font-semibold text-fg">
              {title}
            </Dialog.Title>
            <Dialog.Description className="mt-1 text-sm text-fg-muted">
              {description}
            </Dialog.Description>
            <div className="mt-4">{children}</div>
            {footer ? (
              <div
                data-testid="record-modal-footer"
                className="sticky bottom-0 -mx-4 -mb-4 mt-4 border-t border-border bg-surface px-4 py-3 sm:-mx-6 sm:-mb-6 sm:px-6"
              >
                {footer}
              </div>
            ) : null}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
      {discard ? (
        <ConfirmDialog
          open={discard.open}
          onOpenChange={(next) => {
            if (!next) discard.onCancel();
          }}
          title="Discard changes?"
          description="You have unsaved changes. If you leave now they will be lost."
          confirmLabel="Discard"
          cancelLabel="Keep editing"
          destructive
          onConfirm={discard.onConfirm}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            const target = returnFocusRef.current;
            if (target instanceof HTMLElement && target.isConnected) {
              target.focus();
            }
          }}
        />
      ) : null}
    </>
  );
}
