import { describeChange, type ChangeDescriptionInput } from "../../lib/itemizedMath";
import { ConfirmDialog } from "../ui";

export interface SyncTotalDialogProps extends ChangeDescriptionInput {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void | Promise<void>;
  pending?: boolean;
  /** Current calendar year; defaults to the system clock (injectable for tests). */
  currentYear?: number;
}

/**
 * Confirm dialog for syncing the entered total to the itemized sum
 * (Requirements 9.3, 9.4, 9.9, 16.1). Names the line, tax year, current and
 * new totals, and the signed difference via `describeChange`. For a completed
 * tax year (earlier than the current calendar year) it adds a filed-return
 * warning.
 */
export function SyncTotalDialog({
  open,
  onOpenChange,
  onConfirm,
  pending = false,
  currentYear = new Date().getFullYear(),
  ...change
}: SyncTotalDialogProps) {
  const completed = change.taxYear < currentYear;
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Update ${change.label} total`}
      description={
        <>
          <span className="block">{describeChange(change)}</span>
          {completed ? (
            <span className="mt-2 block font-medium text-fg">
              {change.taxYear} is a completed tax year. If you already filed a
              return for it, your records will no longer match the filed
              return.
            </span>
          ) : null}
        </>
      }
      confirmLabel="Update total"
      destructive={false}
      onConfirm={onConfirm}
      pending={pending}
    />
  );
}
