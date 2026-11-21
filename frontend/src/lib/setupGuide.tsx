import { createContext, useContext, useMemo, type ReactNode } from "react";

/**
 * Setup guide context (Requirements 26.3, 26.4). The shell provides
 * `showSetupGuide` (clears the stored state, navigates to the dashboard and
 * focuses the guide heading) and a `resetSignal` that changes every time the
 * stored state was cleared, so a mounted `ChecklistCard` re-reads its state.
 */
export interface SetupGuideValue {
  showSetupGuide: () => void;
  resetSignal: number;
}

const SetupGuideContext = createContext<SetupGuideValue | null>(null);

export interface SetupGuideProviderProps {
  showSetupGuide: () => void;
  resetSignal: number;
  children: ReactNode;
}

export function SetupGuideProvider({
  showSetupGuide,
  resetSignal,
  children,
}: SetupGuideProviderProps) {
  const value = useMemo(
    () => ({ showSetupGuide, resetSignal }),
    [showSetupGuide, resetSignal],
  );
  return (
    <SetupGuideContext.Provider value={value}>
      {children}
    </SetupGuideContext.Provider>
  );
}

/** Returns the context value, or null when no provider is present. */
export function useSetupGuide(): SetupGuideValue | null {
  return useContext(SetupGuideContext);
}
