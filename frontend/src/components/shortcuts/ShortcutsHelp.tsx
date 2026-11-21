import * as Dialog from "@radix-ui/react-dialog";
import type { Platform } from "../../lib/shortcuts/eligibility";
import { formatKeys, SHORTCUTS } from "../../lib/shortcuts/registry";
import { Button } from "../ui/Button";

export interface ShortcutsHelpProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  platform: Platform;
  /** Focus return handler from the provider, which remembers the opener. */
  onCloseAutoFocus?: (event: Event) => void;
}

const GROUPS = ["General", "Go to"] as const;

/** "Keyboard shortcuts" dialog (ui-polish Requirements 6.5, 6.6). */
export function ShortcutsHelp({
  open,
  onOpenChange,
  platform,
  onCloseAutoFocus,
}: ShortcutsHelpProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-fg/40" />
        <Dialog.Content
          data-palette=""
          onCloseAutoFocus={onCloseAutoFocus}
          className="fixed left-1/2 top-1/2 z-50 max-h-[90dvh] w-[calc(100vw-1.5rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-surface p-4 shadow-card focus:outline-none sm:p-6"
        >
          <Dialog.Title className="text-lg font-semibold text-fg">
            Keyboard shortcuts
          </Dialog.Title>
          <Dialog.Description className="sr-only">
            Keys that open the command palette and jump between pages.
          </Dialog.Description>
          {GROUPS.map((group) => {
            const defs = SHORTCUTS.filter((d) => d.group === group);
            if (defs.length === 0) return null;
            return (
              <section key={group} className="mt-4">
                <h3 className="text-sm font-semibold text-fg">{group}</h3>
                <dl className="mt-2 space-y-2">
                  {defs.map((def) => {
                    const keys = formatKeys(def, platform);
                    return (
                      <div
                        key={def.id}
                        className="flex items-center justify-between gap-4"
                      >
                        <dt className="text-sm text-fg-muted">{def.label}</dt>
                        <dd className="flex items-center gap-1">
                          {keys.map((key, i) => (
                            <span key={`${key}-${i}`} className="contents">
                              {i > 0 && def.keys.length === 2 && def.keys[0] !== "mod" ? (
                                <span className="text-xs text-fg-muted">then</span>
                              ) : i > 0 ? (
                                <span className="text-xs text-fg-muted">+</span>
                              ) : null}
                              <kbd className="rounded border border-border bg-surface-muted px-1.5 py-0.5 font-mono text-xs text-fg">
                                {key}
                              </kbd>
                            </span>
                          ))}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
              </section>
            );
          })}
          <div className="mt-6 flex justify-end">
            <Dialog.Close asChild>
              <Button type="button" variant="secondary">
                Close
              </Button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
