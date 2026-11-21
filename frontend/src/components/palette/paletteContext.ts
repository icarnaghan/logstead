import { createContext, useContext } from "react";

/** Handlers the palette registers with the shortcuts provider while mounted. */
export interface PaletteHandlers {
  open: (initial?: string) => void;
  close: () => void;
  isOpen: () => boolean;
}

export interface PaletteApi {
  openPalette: (initial?: string) => void;
  closePalette: () => void;
  openHelp: () => void;
  /**
   * Called by `PaletteProvider` so the shortcuts provider (which sits outside
   * it) can open and close the palette. Returns the unregister function.
   */
  registerPalette: (handlers: PaletteHandlers) => () => void;
}

const noop = () => {};

export const PaletteContext = createContext<PaletteApi>({
  openPalette: noop,
  closePalette: noop,
  openHelp: noop,
  registerPalette: () => noop,
});

export function usePalette(): PaletteApi {
  return useContext(PaletteContext);
}
