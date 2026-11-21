import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useMatch } from "react-router-dom";
import type { Property } from "../../api/properties";
import { useGuardedNavigate } from "../../lib/navigationGuard";
import { useSetupGuide } from "../../lib/setupGuide";
import type { Platform } from "../../lib/shortcuts/eligibility";
import { usePortfolioYearRange } from "../../lib/usePortfolioYearRange";
import { useTheme } from "../../theme/ThemeProvider";
import { useShellProperties } from "../ShellPropertiesContext";
import { propertyPath } from "../navConfig";
import { useOpenerFocusReturn } from "../ui/useOpenerFocusReturn";
import { CommandPalette, type PickRequest } from "./CommandPalette";
import { isSafeAppLink } from "../../lib/safeLink";
import { usePalette } from "./paletteContext";
import type { SearchFn } from "./useGlobalSearch";
import {
  buildLocalItems,
  isPropertyScopedAction,
  resolveActionTarget,
  type PaletteItem,
  type PropertyScopedActionId,
} from "./paletteItems";

const SEGMENTS: Record<PropertyScopedActionId, string> = {
  "add-transaction": "transactions",
  "add-repair": "repairs",
  "add-asset": "assets",
  "add-loan": "loans",
};

function detectPlatform(): Platform {
  if (typeof navigator === "undefined") return "other";
  return /mac|iphone|ipad|ipod/i.test(navigator.platform || navigator.userAgent)
    ? "mac"
    : "other";
}

export interface PaletteProviderProps {
  children: ReactNode;
  /** Test seams for the tax-year range. */
  loadProperties?: (signal?: AbortSignal) => Promise<readonly Property[]>;
  loadEarliest?: (propertyId: string, signal?: AbortSignal) => Promise<number | null>;
  /** Test seam for the global search request. */
  search?: SearchFn;
}

/**
 * Owns the palette open state and registers it with the shortcuts provider
 * (ui-polish Requirements 1.1 to 1.6, 3.2 to 3.8). Must render inside
 * `ShortcutsProvider`, the router, the theme provider and the shell
 * properties provider.
 */
export function PaletteProvider({
  children,
  loadProperties,
  loadEarliest,
  search,
}: PaletteProviderProps) {
  const { registerPalette, openHelp } = usePalette();
  const { go } = useGuardedNavigate();
  const { toggle } = useTheme();
  const setupGuide = useSetupGuide();
  const { properties, status } = useShellProperties();
  const years = usePortfolioYearRange(loadProperties, loadEarliest);
  const match = useMatch({ path: "/properties/:propertyId", end: false });
  const currentPropertyId = match?.params.propertyId ?? null;
  const platform = useMemo(detectPlatform, []);
  const { rememberOpener, handleCloseAutoFocus } = useOpenerFocusReturn();

  const [open, setOpenState] = useState(false);
  const [initialQuery, setInitialQuery] = useState("");
  const openRef = useRef(false);
  /** True when the palette closed to navigate, so the route owns focus. */
  const navigatedRef = useRef(false);
  const helpAfterCloseRef = useRef(false);

  const setOpen = useCallback((next: boolean) => {
    openRef.current = next;
    setOpenState(next);
  }, []);

  const openPalette = useCallback(
    (initial?: string) => {
      if (!openRef.current) {
        rememberOpener();
        navigatedRef.current = false;
        helpAfterCloseRef.current = false;
      }
      setInitialQuery(initial ?? "");
      setOpen(true);
    },
    [rememberOpener, setOpen],
  );
  const closePalette = useCallback(() => setOpen(false), [setOpen]);

  useEffect(
    () =>
      registerPalette({
        open: openPalette,
        close: closePalette,
        isOpen: () => openRef.current,
      }),
    [registerPalette, openPalette, closePalette],
  );

  const items = useMemo(() => {
    const local = buildLocalItems({
      properties,
      years,
      currentPropertyId,
      platform,
      hasProperty: properties.length > 0,
    });
    return setupGuide
      ? local
      : local.filter((item) => item.id !== "show-setup-guide");
  }, [properties, years, currentPropertyId, platform, setupGuide]);

  const navigateAndClose = useCallback(
    (to: string) => {
      navigatedRef.current = true;
      setOpen(false);
      go(to);
    },
    [go, setOpen],
  );

  const showSetupGuide = setupGuide?.showSetupGuide;
  const onRunItem = useCallback(
    (item: PaletteItem): PickRequest | void => {
      if (item.kind === "destination") {
        navigateAndClose(item.to);
        return;
      }
      if (isPropertyScopedAction(item.id)) {
        const target = resolveActionTarget(item.id, properties, currentPropertyId);
        if (target.kind === "navigate") navigateAndClose(target.to);
        else if (target.kind === "pickProperty") return { pick: item.id };
        return;
      }
      switch (item.id) {
        case "add-property":
          navigateAndClose("/properties?new=1");
          break;
        case "import-schedule-e":
          navigateAndClose("/imports/schedule-e");
          break;
        case "download-backup":
          navigateAndClose("/profile?focus=backup");
          break;
        case "switch-theme":
          setOpen(false);
          toggle();
          break;
        case "keyboard-shortcuts":
          helpAfterCloseRef.current = true;
          setOpen(false);
          break;
        case "show-setup-guide":
          navigatedRef.current = true;
          setOpen(false);
          showSetupGuide?.();
          break;
        default:
      }
    },
    [properties, currentPropertyId, navigateAndClose, setOpen, toggle, showSetupGuide],
  );

  const onPickProperty = useCallback(
    (action: PropertyScopedActionId, propertyId: string) => {
      navigateAndClose(`${propertyPath(propertyId, SEGMENTS[action])}?new=1`);
    },
    [navigateAndClose],
  );

  const onOpenLink = useCallback(
    (link: string) => {
      if (isSafeAppLink(link)) navigateAndClose(link);
    },
    [navigateAndClose],
  );

  const onCloseAutoFocus = useCallback(
    (event: Event) => {
      if (navigatedRef.current) {
        // Focus placement is left to the route change (Requirement 1.6).
        event.preventDefault();
        return;
      }
      handleCloseAutoFocus(event);
      if (helpAfterCloseRef.current) {
        helpAfterCloseRef.current = false;
        openHelp();
      }
    },
    [handleCloseAutoFocus, openHelp],
  );

  return (
    <>
      {children}
      <CommandPalette
        open={open}
        onOpenChange={setOpen}
        initialQuery={initialQuery}
        items={items}
        properties={properties}
        propertiesStatus={status}
        onRunItem={onRunItem}
        onPickProperty={onPickProperty}
        onCloseAutoFocus={onCloseAutoFocus}
        onOpenLink={onOpenLink}
        search={search}
      />
    </>
  );
}
