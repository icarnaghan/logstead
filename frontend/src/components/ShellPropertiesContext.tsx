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
import { listProperties, type Property } from "../api/properties";
import { useFirstLoad } from "./ui";

/** Load status of the shell-level property list. */
export type ShellPropertiesStatus = "loading" | "loaded" | "error";

export interface ShellPropertiesValue {
  properties: Property[];
  status: ShellPropertiesStatus;
  /** Re-fetch the list without clearing what is shown. */
  reload: () => void;
  /** Alias of `reload` (design name). */
  refresh: () => void;
}

const noop = () => {};

/** Default for standalone renders: nothing loaded, reload is a no-op. */
const DEFAULT_VALUE: ShellPropertiesValue = {
  properties: [],
  status: "loading",
  reload: noop,
  refresh: noop,
};

const ShellPropertiesContext =
  createContext<ShellPropertiesValue>(DEFAULT_VALUE);

interface ProviderProps {
  children: ReactNode;
  /** Test seam: defaults to the real `listProperties`. */
  load?: (signal?: AbortSignal) => Promise<Property[]>;
}

/**
 * Loads the user's properties once for the whole shell. Skeleton-only-on-first
 * load: after a successful load, refreshes and refresh errors keep the
 * existing list (Requirement 19.9).
 */
export function ShellPropertiesProvider({
  children,
  load = listProperties,
}: ProviderProps) {
  const [properties, setProperties] = useState<Property[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const view = useFirstLoad({ loading, error });
  const controllerRef = useRef<AbortController | null>(null);

  const run = useCallback(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    setError(null);
    load(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setProperties(result);
        setLoading(false);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setError("Could not load properties.");
        setLoading(false);
      });
  }, [load]);

  useEffect(() => {
    run();
    return () => controllerRef.current?.abort();
  }, [run]);

  const status: ShellPropertiesStatus = view.showContent
    ? "loaded"
    : error !== null
      ? "error"
      : "loading";

  const value = useMemo<ShellPropertiesValue>(
    () => ({ properties, status, reload: run, refresh: run }),
    [properties, status, run],
  );

  return (
    <ShellPropertiesContext.Provider value={value}>
      {children}
    </ShellPropertiesContext.Provider>
  );
}

export function useShellProperties(): ShellPropertiesValue {
  return useContext(ShellPropertiesContext);
}
