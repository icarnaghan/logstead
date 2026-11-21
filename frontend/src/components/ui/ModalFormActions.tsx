import { cn } from "../../lib/cn";

export interface ModalFormActionsProps {
  children: React.ReactNode;
  className?: string;
}

/**
 * Action bar (Cancel and Save) for a form rendered inside `RecordModal`.
 *
 * It stays inside the `<form>` so submit buttons keep working, and sticks to
 * the bottom of the modal's scrolling panel so Save stays reachable on short
 * viewports (for example 320px wide phones with the keyboard open). The
 * negative margins cancel the panel padding in `RecordModal` so the bar spans
 * the full panel width. Buttons wrap instead of overflowing at 320px.
 */
export function ModalFormActions({
  children,
  className,
}: ModalFormActionsProps) {
  return (
    <div
      className={cn(
        "sticky bottom-0 -mx-4 -mb-4 flex flex-wrap justify-end gap-2 border-t border-border bg-surface px-4 py-3 sm:-mx-6 sm:-mb-6 sm:px-6",
        className,
      )}
    >
      {children}
    </div>
  );
}
