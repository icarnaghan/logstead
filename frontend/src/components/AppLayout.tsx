import { useState } from "react";
import { Outlet } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { MainNav } from "./MainNav";
import { ProfileMenu } from "./ProfileMenu";

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
 *   close, and returns focus to the toggle on close.
 * - Numbers-and-forms aesthetic: plain, high-contrast styling, no charts.
 */
export default function AppLayout() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="min-h-screen bg-canvas text-fg">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-accent focus:px-4 focus:py-2 focus:text-accent-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
      >
        Skip to main content
      </a>

      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3">
          <Dialog.Root open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
            <Dialog.Trigger asChild>
              <button
                type="button"
                aria-controls="mobile-nav"
                aria-expanded={mobileNavOpen}
                className="rounded-md p-2 text-fg-muted hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent md:hidden"
              >
                <span aria-hidden="true" className="block h-4 w-5">
                  <span className="mb-1 block h-0.5 w-5 bg-current" />
                  <span className="mb-1 block h-0.5 w-5 bg-current" />
                  <span className="block h-0.5 w-5 bg-current" />
                </span>
                <span className="sr-only">Open navigation menu</span>
              </button>
            </Dialog.Trigger>

            <Dialog.Portal>
              <Dialog.Overlay className="fixed inset-0 z-40 bg-slate-900/40 md:hidden" />
              <Dialog.Content
                id="mobile-nav"
                aria-label="Main navigation"
                className="fixed inset-y-0 left-0 z-50 w-72 max-w-[80%] bg-surface p-4 shadow-card focus:outline-none md:hidden"
              >
                <div className="mb-4 flex items-center justify-between">
                  <Dialog.Title className="text-lg font-semibold">
                    Menu
                  </Dialog.Title>
                  <Dialog.Close asChild>
                    <button
                      type="button"
                      className="rounded-md p-2 text-fg-muted hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    >
                      <span aria-hidden="true">×</span>
                      <span className="sr-only">Close navigation menu</span>
                    </button>
                  </Dialog.Close>
                </div>
                <Dialog.Description className="sr-only">
                  Primary navigation links
                </Dialog.Description>
                <nav aria-label="Main">
                  <MainNav onNavigate={() => setMobileNavOpen(false)} />
                </nav>
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>

          <span className="text-xl font-semibold">Logstead</span>

          <div className="ml-auto">
            <ProfileMenu />
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-6xl gap-6 px-4 py-6">
        <aside className="hidden w-56 shrink-0 md:block">
          <nav aria-label="Primary">
            <MainNav />
          </nav>
        </aside>

        <main id="main-content" tabIndex={-1} className="min-w-0 flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
