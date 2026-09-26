import { useNavigate } from "react-router-dom";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { getUserProfile, logout } from "../lib/auth";
import { ThemeToggle } from "./ThemeToggle";

/**
 * Top-right profile menu.
 *
 * A round avatar button (the user's first initial) opens a Radix
 * `DropdownMenu` showing the signed-in user's email, a link to the profile
 * page, and a sign-out action. Radix handles keyboard navigation, focus
 * management, and `Esc`-to-close.
 *
 * Accessibility: the trigger has an accessible name; the visible initial is
 * decorative (`aria-hidden`).
 */
export function ProfileMenu() {
  const navigate = useNavigate();
  const profile = getUserProfile();

  const label = profile?.displayName ?? "Account";
  const initial = (profile?.email ?? profile?.sub ?? "?")
    .trim()
    .charAt(0)
    .toUpperCase();

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className="flex h-9 w-9 items-center justify-center rounded-full bg-accent text-sm font-semibold text-accent-fg hover:bg-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <span aria-hidden="true">{initial}</span>
          <span className="sr-only">Open account menu for {label}</span>
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="z-50 min-w-60 rounded-lg border border-border bg-surface p-1 shadow-card focus:outline-none"
        >
          <div className="px-3 py-2">
            <p className="text-xs text-fg-subtle">Signed in as</p>
            <p className="truncate text-sm font-medium text-fg">
              {label}
            </p>
          </div>

          <DropdownMenu.Separator className="my-1 h-px bg-border" />

          <ThemeToggle />

          <DropdownMenu.Separator className="my-1 h-px bg-border" />

          <DropdownMenu.Item
            onSelect={() => navigate("/profile")}
            className="cursor-pointer rounded-md px-3 py-2 text-sm text-fg-muted outline-none data-[highlighted]:bg-surface-muted data-[highlighted]:text-fg"
          >
            Profile &amp; settings
          </DropdownMenu.Item>

          <DropdownMenu.Item
            onSelect={() => logout()}
            className="cursor-pointer rounded-md px-3 py-2 text-sm text-fg-muted outline-none data-[highlighted]:bg-surface-muted data-[highlighted]:text-fg"
          >
            Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
