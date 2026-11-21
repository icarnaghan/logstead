import * as Dialog from "@radix-ui/react-dialog";
import { cn } from "../../lib/cn";

export interface PhotoLightboxProps {
  /** Whether the lightbox is open. */
  open: boolean;
  /** Called to open/close; closing fires on Escape, backdrop click, or the ✕. */
  onOpenChange: (open: boolean) => void;
  /** The full-size image URL to display (a pre-signed S3 GET URL). */
  src: string;
  /** Accessible alt text / dialog title for the image. */
  alt: string;
}

/**
 * Full-screen photo viewer built on `@radix-ui/react-dialog`, so it inherits
 * the focus trap, `Esc`-to-close, backdrop-click-to-close, and focus-return for
 * free — matching the app's other modals ({@link ConfirmDialog}).
 *
 * The image is shown at its natural aspect ratio, bounded to the viewport, over
 * a dimmed backdrop. A close button sits top-right. The dialog is labelled by
 * the image's alt text so assistive tech announces what is shown.
 */
export function PhotoLightbox({ open, onOpenChange, src, alt }: PhotoLightboxProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-fg/70" />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2",
            "flex max-h-[90vh] max-w-[90vw] flex-col focus:outline-none",
          )}
        >
          {/* The alt text doubles as the dialog's accessible title. */}
          <Dialog.Title className="sr-only">{alt}</Dialog.Title>
          <Dialog.Close
            aria-label="Close photo"
            className={cn(
              "absolute -top-3 -right-3 z-10 flex h-9 w-9 items-center justify-center rounded-full max-md:h-11 max-md:w-11",
              "border border-border bg-surface text-lg font-medium text-fg shadow-card",
              "hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
            )}
          >
            <span aria-hidden="true">✕</span>
          </Dialog.Close>
          <img
            src={src}
            alt={alt}
            className="max-h-[90vh] max-w-[90vw] rounded-lg object-contain shadow-card"
          />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default PhotoLightbox;
