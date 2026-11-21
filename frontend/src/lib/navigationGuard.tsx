import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";

interface GuardValue {
  setDirty: (key: string, dirty: boolean) => void;
  isDirty: () => boolean;
  request: (to: string, onProceed?: () => void) => void;
}

const noop: GuardValue = {
  setDirty: () => {},
  isDirty: () => false,
  request: () => {},
};

const NavigationGuardContext = createContext<GuardValue | null>(null);

/**
 * Holds the dirty flags registered by `useRegisterDirty` and renders the
 * shared "Discard changes?" confirm used by guarded navigation.
 */
export function NavigationGuardProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const flags = useRef(new Map<string, boolean>());
  const [pending, setPending] = useState<{
    to: string;
    onProceed?: () => void;
  } | null>(null);

  const setDirty = useCallback((key: string, dirty: boolean) => {
    if (dirty) flags.current.set(key, true);
    else flags.current.delete(key);
  }, []);
  const isDirty = useCallback(() => flags.current.size > 0, []);
  const request = useCallback(
    (to: string, onProceed?: () => void) => {
      if (flags.current.size > 0) setPending({ to, onProceed });
      else {
        navigate(to);
        onProceed?.();
      }
    },
    [navigate],
  );
  const value = useMemo(
    () => ({ setDirty, isDirty, request }),
    [setDirty, isDirty, request],
  );

  return (
    <NavigationGuardContext.Provider value={value}>
      {children}
      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
        title="Discard changes?"
        description="You have unsaved changes. Leaving this page will discard them."
        confirmLabel="Discard"
        cancelLabel="Keep editing"
        onConfirm={() => {
          const current = pending;
          setPending(null);
          if (current !== null) {
            flags.current.clear();
            navigate(current.to);
            current.onProceed?.();
          }
        }}
      />
    </NavigationGuardContext.Provider>
  );
}

/** Registers a dirty flag under `key` while mounted; cleared on unmount. */
export function useRegisterDirty(key: string, dirty: boolean): void {
  const guard = useContext(NavigationGuardContext) ?? noop;
  const { setDirty } = guard;
  useEffect(() => {
    setDirty(key, dirty);
    return () => setDirty(key, false);
  }, [setDirty, key, dirty]);
}

/** Returns `go(to)`: navigates at once when clean, else asks to discard first. */
export function useGuardedNavigate(): {
  go: (to: string, onProceed?: () => void) => void;
} {
  const fallback = useNavigate();
  const guard = useContext(NavigationGuardContext);
  const request = guard?.request;
  const go = useCallback(
    (to: string, onProceed?: () => void) => {
      if (request) request(to, onProceed);
      else {
        fallback(to);
        onProceed?.();
      }
    },
    [request, fallback],
  );
  return useMemo(() => ({ go }), [go]);
}
