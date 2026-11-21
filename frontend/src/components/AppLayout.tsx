import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { getUserProfile } from "../lib/auth";
import { clearSetupState } from "../lib/onboardingStorage";
import { SetupGuideProvider } from "../lib/setupGuide";
import { Link, Outlet, useLocation } from "react-router-dom";
import { AppErrorBoundary } from "./AppErrorBoundary";
import { BrandLogo } from "./brand/BrandLogo";
import * as Dialog from "@radix-ui/react-dialog";
import { MainNav } from "./MainNav";
import { ProfileMenu } from "./ProfileMenu";
import { PropertySwitcher } from "./PropertySwitcher";
import { RouteAnnouncer } from "./RouteAnnouncer";
import { ShellPropertiesProvider } from "./ShellPropertiesContext";
import { NavigationGuardProvider, useGuardedNavigate } from "../lib/navigationGuard";
import { PaletteProvider } from "./palette/PaletteProvider";
import { usePalette } from "./palette/paletteContext";
import { ShortcutsProvider } from "./shortcuts/ShortcutsProvider";
import { Button, FOCUS_RING, MenuIcon, SearchIcon, XIcon } from "./ui";

/**
 * The application shell: a responsive header + navigation + main content
 * region shared by every route.
 *
 * Layout (Requirement 14.2):
 * - `<768px` (single column): a header with a mobile menu toggle that opens a
 *   Radix `Dialog` drawer containing the primary navigation.
 * - `>=768px` (multi column): the mobile toggle is hidden and a persistent
 *   sidebar navigation sits beside the main content.
 *
 * Accessibility (Requirement 14.1, 14.4):
 * - A "Skip to main content" link is the first focusable element.
 * - Semantic landmarks: `<header>`, `<nav>` (labelled), and `<main>`.
 * - The mobile toggle is a real button with `aria-expanded`/`aria-controls`
 *   and an accessible name; Radix `Dialog` manages focus trapping, `Esc` to
 *   close, and returns focus to the toggle on Esc/close. Choosing a destination skips that
 *   focus return so the route change can focus the new page h1.
 * - Numbers-and-forms aesthetic: plain, high-contrast styling, no charts.
 */
export default function AppLayout() {
  return (
    <NavigationGuardProvider>
      <SetupGuideHost>
        <ShellPropertiesProvider>
          <ShortcutsProvider>
            <PaletteProvider>
              <Shell />
            </PaletteProvider>
          </ShortcutsProvider>
        </ShellPropertiesProvider>
      </SetupGuideHost>
    </NavigationGuardProvider>
  );
}

/** Longest wait for the checklist heading to render after "Show setup guide". */
const FOCUS_WAIT_MS = 5000;

/**
 * Provides `SetupGuideContext` (Requirements 26.3, 26.4): clears the stored
 * setup state, navigates to the dashboard and focuses the guide heading once
 * it is rendered.
 */
function SetupGuideHost({ children }: { children: ReactNode }) {
  const { go } = useGuardedNavigate();
  const [resetSignal, setResetSignal] = useState(0);
  const cancelFocus = useRef<(() => void) | null>(null);

  useEffect(() => () => cancelFocus.current?.(), []);

  const showSetupGuide = useCallback(() => {
    clearSetupState(getUserProfile()?.sub);
    setResetSignal((n) => n + 1);
    go("/");

    cancelFocus.current?.();
    let frame = 0;
    const started = performance.now();
    const attempt = () => {
      const heading = document.getElementById("checklist-heading");
      if (heading) {
        heading.focus();
        // Stop once focus landed (a route-change focus may still win the first frame).
        if (document.activeElement === heading) {
          cancelFocus.current = null;
          return;
        }
      }
      if (performance.now() - started < FOCUS_WAIT_MS) {
        frame = requestAnimationFrame(attempt);
      }
    };
    frame = requestAnimationFrame(attempt);
    cancelFocus.current = () => cancelAnimationFrame(frame);
  }, [go]);

  return (
    <SetupGuideProvider showSetupGuide={showSetupGuide} resetSignal={resetSignal}>
      {children}
    </SetupGuideProvider>
  );
}

function Shell() {
  const { openPalette } = usePalette();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { pathname } = useLocation();
  // True when the drawer closed because a destination was chosen; the route
  // change then moves focus to the new page h1 instead of the menu button.
  const closedByNavigation = useRef(false);

  return (
    <div className="min-h-screen bg-canvas text-fg">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-accent focus:px-4 focus:py-2 focus:text-accent-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-fg"
      >
        Skip to main content
      </a>

      <header className="border-b border-border bg-surface print:hidden">
        <div className="mx-auto flex max-w-screen-2xl items-center gap-3 px-4 py-3">
          <Dialog.Root open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
            <Dialog.Trigger asChild>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Open navigation menu"
                aria-controls="mobile-nav"
                aria-expanded={mobileNavOpen}
                className="md:hidden"
              >
                <MenuIcon className="h-5 w-5" aria-hidden="true" />
              </Button>
            </Dialog.Trigger>

            <Dialog.Portal>
              <Dialog.Overlay className="fixed inset-0 z-40 bg-fg/40 md:hidden print:hidden" />
              <Dialog.Content
                id="mobile-nav"
                aria-label="Main navigation"
                onCloseAutoFocus={(event) => {
                  if (closedByNavigation.current) {
                    event.preventDefault();
                    closedByNavigation.current = false;
                  }
                }}
                className="fixed inset-y-0 left-0 z-50 w-72 max-w-[80%] bg-surface p-4 shadow-card focus:outline-none md:hidden print:hidden"
              >
                <div className="mb-4 flex items-center justify-between">
                  <Dialog.Title className="text-lg font-semibold">
                    Menu
                  </Dialog.Title>
                  <Dialog.Close asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Close menu"
                    >
                      <XIcon className="h-5 w-5" aria-hidden="true" />
                    </Button>
                  </Dialog.Close>
                </div>
                <Dialog.Description className="sr-only">
                  Primary navigation links
                </Dialog.Description>
                <PropertySwitcher className="mb-4 sm:hidden" />
                <nav aria-label="Main">
                  <MainNav
                    onNavigate={() => {
                      closedByNavigation.current = true;
                      setMobileNavOpen(false);
                    }}
                  />
                </nav>
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>

          <Link
            to="/"
            aria-label="Logstead home"
            className={`inline-flex items-center rounded-md ${FOCUS_RING}`}
          >
            <BrandLogo decorative className="h-8 w-auto sm:h-10" />
          </Link>

          <PropertySwitcher className="hidden sm:block" />

          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              aria-label="Search"
              aria-keyshortcuts="Control+K Meta+K"
              onClick={() => openPalette()}
            >
              <SearchIcon className="h-5 w-5" aria-hidden="true" />
            </Button>
            <ProfileMenu />
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-screen-2xl gap-6 px-4 py-6">
        <aside className="hidden w-56 shrink-0 md:block print:hidden">
          <nav aria-label="Primary">
            <MainNav />
          </nav>
        </aside>

        <main id="main-content" tabIndex={-1} className="min-w-0 flex-1">
          {/* Keyed by path so a crashed page resets on navigation; the shell stays. */}
          <AppErrorBoundary key={pathname} scope="route">
            <Outlet />
          </AppErrorBoundary>
        </main>
      </div>
      <RouteAnnouncer />
    </div>
  );
}
