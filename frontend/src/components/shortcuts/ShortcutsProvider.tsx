import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  classifyTarget,
  hasBlockingDialog,
  isEligiblePlainKey,
  isPaletteChord,
  type KeyEventInfo,
  type Platform,
} from "../../lib/shortcuts/eligibility";
import {
  SHORTCUTS,
  type ShortcutActionId,
  type ShortcutDef,
} from "../../lib/shortcuts/registry";
import {
  INITIAL_SEQUENCE_STATE,
  SEQUENCE_TIMEOUT_MS,
  stepSequence,
  type SequenceState,
} from "../../lib/shortcuts/sequence";
import { useGuardedNavigate } from "../../lib/navigationGuard";
import {
  PaletteContext,
  type PaletteApi,
  type PaletteHandlers,
} from "../palette/paletteContext";
import { useOpenerFocusReturn } from "../ui/useOpenerFocusReturn";
import { ShortcutsHelp } from "./ShortcutsHelp";

const GO_TARGETS: Partial<Record<ShortcutActionId, string>> = {
  goDashboard: "/",
  goProperties: "/properties",
  goReports: "/reports",
  goCarryforward: "/carryforward",
  goImport: "/imports/schedule-e",
  goActivity: "/activity",
};

function detectPlatform(): Platform {
  if (typeof navigator === "undefined") return "other";
  return /mac|iphone|ipad|ipod/i.test(navigator.platform || navigator.userAgent)
    ? "mac"
    : "other";
}

/**
 * Owns the single `document` keydown listener, the help dialog, and the
 * palette context (ui-polish Requirements 6.1 to 6.7, 7.1, 7.2, 7.8, 7.9).
 * The palette registers its open and close handlers through the context.
 */
export function ShortcutsProvider({ children }: { children: ReactNode }) {
  const { go } = useGuardedNavigate();
  const platform = useMemo(detectPlatform, []);
  const [helpOpen, setHelpOpen] = useState(false);
  const { rememberOpener, handleCloseAutoFocus } = useOpenerFocusReturn();
  const paletteRef = useRef<PaletteHandlers | null>(null);
  const sequenceRef = useRef<SequenceState>(INITIAL_SEQUENCE_STATE);

  const openPalette = useCallback((initial?: string) => {
    paletteRef.current?.open(initial);
  }, []);
  const closePalette = useCallback(() => {
    paletteRef.current?.close();
  }, []);
  const openHelp = useCallback(() => {
    rememberOpener();
    setHelpOpen(true);
  }, [rememberOpener]);
  const registerPalette = useCallback((handlers: PaletteHandlers) => {
    paletteRef.current = handlers;
    return () => {
      if (paletteRef.current === handlers) paletteRef.current = null;
    };
  }, []);

  // Latest callbacks for the stable listener.
  const actionsRef = useRef({ go, openPalette, openHelp });
  useEffect(() => {
    actionsRef.current = { go, openPalette, openHelp };
  });

  useEffect(() => {
    function run(def: ShortcutDef, event: KeyboardEvent) {
      const { go: goTo, openPalette: open, openHelp: help } = actionsRef.current;
      if (def.run === "openSearch") {
        event.preventDefault();
        open();
      } else if (def.run === "openHelp") {
        event.preventDefault();
        help();
      } else if (def.run === "openPalette") {
        event.preventDefault();
        open();
      } else {
        const to = GO_TARGETS[def.run];
        if (to) {
          event.preventDefault();
          goTo(to);
        }
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      const info: KeyEventInfo = {
        key: event.key,
        keyCode: event.keyCode,
        target: classifyTarget(event.target),
        alt: event.altKey,
        ctrl: event.ctrlKey,
        meta: event.metaKey,
        shift: event.shiftKey,
        isComposing: event.isComposing,
        repeat: event.repeat,
        defaultPrevented: event.defaultPrevented,
        blockingDialogOpen: hasBlockingDialog(document),
      };

      if (isPaletteChord(info, platform)) {
        event.preventDefault();
        sequenceRef.current = INITIAL_SEQUENCE_STATE;
        const palette = paletteRef.current;
        if (palette?.isOpen()) palette.close();
        else palette?.open();
        return;
      }

      // Bare modifier presses do not affect a pending sequence.
      if (event.key.length !== 1) return;
      if (!isEligiblePlainKey(info)) {
        sequenceRef.current = INITIAL_SEQUENCE_STATE;
        return;
      }

      const single = SHORTCUTS.find(
        (d) => d.keys.length === 1 && d.keys[0] === event.key,
      );
      if (single) {
        sequenceRef.current = INITIAL_SEQUENCE_STATE;
        run(single, event);
        return;
      }

      const result = stepSequence(
        sequenceRef.current,
        event.key,
        Date.now(),
        SHORTCUTS,
        SEQUENCE_TIMEOUT_MS,
      );
      sequenceRef.current = result.state;
      if (result.fired) run(result.fired, event);
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [platform]);

  const value = useMemo<PaletteApi>(
    () => ({ openPalette, closePalette, openHelp, registerPalette }),
    [openPalette, closePalette, openHelp, registerPalette],
  );

  return (
    <PaletteContext.Provider value={value}>
      {children}
      <ShortcutsHelp
        open={helpOpen}
        onOpenChange={setHelpOpen}
        platform={platform}
        onCloseAutoFocus={handleCloseAutoFocus}
      />
    </PaletteContext.Provider>
  );
}
