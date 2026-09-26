import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProfileMenu } from "./ProfileMenu";
import { ThemeProvider } from "../theme/ThemeProvider";
import * as auth from "../lib/auth";

/**
 * Tests for the top-right profile menu. The signed-in user is derived from the
 * ID token via getUserProfile; sign-out delegates to auth.logout. Both are
 * stubbed so no real token or navigation is required.
 */
function renderMenu() {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <ProfileMenu />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ProfileMenu", () => {
  it("shows the user's initial and an accessible trigger name", () => {
    vi.spyOn(auth, "getUserProfile").mockReturnValue({
      sub: "user-1",
      email: "you@example.com",
      displayName: "you@example.com",
    });

    renderMenu();

    const trigger = screen.getByRole("button", { name: /account menu/i });
    expect(trigger).toHaveTextContent("Y");
  });

  it("reveals the email and sign-out action when opened", async () => {
    const user = userEvent.setup();
    vi.spyOn(auth, "getUserProfile").mockReturnValue({
      sub: "user-1",
      email: "you@example.com",
      displayName: "you@example.com",
    });

    renderMenu();
    await user.click(screen.getByRole("button", { name: /account menu/i }));

    expect(screen.getByText("you@example.com")).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: /profile & settings/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: /sign out/i }),
    ).toBeInTheDocument();
  });

  it("calls logout when Sign out is chosen", async () => {
    const user = userEvent.setup();
    vi.spyOn(auth, "getUserProfile").mockReturnValue({
      sub: "user-1",
      displayName: "user-1",
    });
    const logoutSpy = vi.spyOn(auth, "logout").mockImplementation(() => {});

    renderMenu();
    await user.click(screen.getByRole("button", { name: /account menu/i }));
    await user.click(screen.getByRole("menuitem", { name: /sign out/i }));

    expect(logoutSpy).toHaveBeenCalledOnce();
  });

  it("falls back to a generic label when there is no session", () => {
    vi.spyOn(auth, "getUserProfile").mockReturnValue(null);
    renderMenu();
    expect(
      screen.getByRole("button", { name: /account menu for account/i }),
    ).toBeInTheDocument();
  });
});
