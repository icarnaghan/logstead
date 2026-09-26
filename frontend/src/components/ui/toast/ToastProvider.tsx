import * as Toast from "@radix-ui/react-toast";
import { createContext, useCallback, useMemo, useRef, useState } from "react";
import { cn } from "../../../lib/cn";

/** The two visual/semantic flavors of a toast. */
export type ToastVariant = "success" | "error";

/** A toast currently held in the provider's queue. */
export interface ToastMessage {
  id: string;
  variant: ToastVariant;
  title: string;
  description?: string;
}

/** Public surface exposed through {@link ToastContext}. */
export interface ToastContextValue {
  /** Enqueue a toast; Radix handles the timers, dismissal, and aria-live. */
  notify: (t: Omit<ToastMessage, "id">) => void;
}

/**
 * Context providing `notify(...)`. Kept `undefined` by default so `useToast`
 * can throw a clear error when used outside the provider.
 */
export const ToastContext = createContext<ToastContextValue | undefined>(
  undefined,
);

/** Token-only styling per variant (Requirement 5.5). No raw palette. */
const VARIANT_CLASSES: Record<ToastVariant, string> = {
  success: "border-success bg-success-subtle text-fg",
  error: "border-danger bg-danger-subtle text-fg",
};

const ROOT_CLASSES = cn(
  "rounded-lg border p-4 shadow-card",
  // Swipe/close animations map to Radix data-state attributes.
  "data-[state=open]:animate-in data-[state=closed]:animate-out",
);

/**
 * Mounts a single Radix `Toast.Provider` + `Toast.Viewport` and exposes
 * `notify(...)` via context (design: "Toast + ToastProvider", Req 5).
 *
 * Radix supplies the `aria-live` region, auto-dismiss timers,
 * pause-on-hover/focus, and swipe/keyboard dismissal; we only manage the queue
 * of active toasts and their token-based styling. Mounted once in `main.tsx`
 * inside `ThemeProvider`, wrapping `App`, so any component can call
 * `useToast().notify(...)`.
 */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const nextId = useRef(0);

  const notify = useCallback((t: Omit<ToastMessage, "id">) => {
    const id = `toast-${nextId.current++}`;
    setToasts((prev) => [...prev, { ...t, id }]);
  }, []);

  const handleOpenChange = useCallback((id: string, open: boolean) => {
    // Drop the toast from state once Radix has finished closing it.
    if (!open) {
      setToasts((prev) => prev.filter((toast) => toast.id !== id));
    }
  }, []);

  const value = useMemo<ToastContextValue>(() => ({ notify }), [notify]);

  return (
    <ToastContext.Provider value={value}>
      <Toast.Provider swipeDirection="right">
        {children}
        {toasts.map((toast) => (
          <Toast.Root
            key={toast.id}
            className={cn(ROOT_CLASSES, VARIANT_CLASSES[toast.variant])}
            onOpenChange={(open) => handleOpenChange(toast.id, open)}
          >
            <Toast.Title className="text-sm font-medium">
              {toast.title}
            </Toast.Title>
            {toast.description ? (
              <Toast.Description className="mt-1 text-sm text-fg-muted">
                {toast.description}
              </Toast.Description>
            ) : null}
          </Toast.Root>
        ))}
        <Toast.Viewport className="fixed bottom-0 right-0 z-50 m-4 flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-2 outline-none" />
      </Toast.Provider>
    </ToastContext.Provider>
  );
}
