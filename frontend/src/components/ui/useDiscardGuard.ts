import { useCallback, useState } from "react";

/**
 * Discard-changes guard (Requirements 10.2-10.5).
 *
 * `requestClose` closes immediately when the form is clean; otherwise it opens
 * the confirmation. Confirming closes the confirmation and the surface;
 * cancelling only dismisses the confirmation so edits are retained.
 */
export interface DiscardGuard {
  requestClose(): void;
  discard: { open: boolean; onConfirm(): void; onCancel(): void };
}

export function useDiscardGuard(opts: {
  dirty: boolean;
  onClose: () => void;
}): DiscardGuard {
  const { dirty, onClose } = opts;
  const [open, setOpen] = useState(false);

  const requestClose = useCallback(() => {
    if (dirty) {
      setOpen(true);
    } else {
      onClose();
    }
  }, [dirty, onClose]);

  const onConfirm = useCallback(() => {
    setOpen(false);
    onClose();
  }, [onClose]);

  const onCancel = useCallback(() => {
    setOpen(false);
  }, []);

  return { requestClose, discard: { open, onConfirm, onCancel } };
}
