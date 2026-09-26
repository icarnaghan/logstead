/**
 * Theme (light/dark) management.
 *
 * A `ThemeProvider` tracks the user's preference — "light", "dark", or
 * "system" — persists an explicit choice in localStorage, and applies the
 * resolved theme by toggling the `.dark` class on <html> (Tailwind
 * `darkMode: "class"`). "system" follows the OS `prefers-color-scheme` live.
 *
 * The default is "system" so a first-time visitor matches their OS setting;
 * choosing light or dark persists until they pick "system" again.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "logstead.theme";

interface ThemeContextValue {
  /** The user's stored preference (may be "system"). */
  preference: ThemePreference;
  /** The concrete theme currently applied ("light" | "dark"). */
  resolved: ResolvedTheme;
  /** Set an explicit preference (persisted). */
  setPreference: (preference: ThemePreference) => void;
  /** Convenience: flip between light and dark (sets an explicit preference). */
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function prefersDark(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

function readStoredPreference(): ThemePreference {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark" || raw === "system") return raw;
  } catch {
    // localStorage unavailable — fall through to system.
  }
  return "system";
}

function resolve(preference: ThemePreference): ResolvedTheme {
  if (preference === "system") return prefersDark() ? "dark" : "light";
  return preference;
}

/** Apply the resolved theme to the document element. */
function applyTheme(resolved: ResolvedTheme): void {
  const root = document.documentElement;
  root.classList.toggle("dark", resolved === "dark");
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(
    readStoredPreference,
  );
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    resolve(preference),
  );

  // Apply on mount and whenever the resolved theme changes.
  useEffect(() => {
    applyTheme(resolved);
  }, [resolved]);

  // Recompute the resolved theme when the preference changes.
  useEffect(() => {
    setResolved(resolve(preference));
  }, [preference]);

  // When following the system, react to OS changes live.
  useEffect(() => {
    if (preference !== "system") return;
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setResolved(media.matches ? "dark" : "light");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [preference]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    try {
      if (next === "system") window.localStorage.removeItem(STORAGE_KEY);
      else window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Persistence best-effort; the in-memory preference still applies.
    }
  }, []);

  const toggle = useCallback(() => {
    setPreference(resolve(preference) === "dark" ? "light" : "dark");
  }, [preference, setPreference]);

  const value = useMemo<ThemeContextValue>(
    () => ({ preference, resolved, setPreference, toggle }),
    [preference, resolved, setPreference, toggle],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/** Access the current theme and controls. Must be used within ThemeProvider. */
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (ctx === null) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return ctx;
}
