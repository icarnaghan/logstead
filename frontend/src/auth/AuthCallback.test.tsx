import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import AuthCallback from "./AuthCallback";

/**
 * Component tests for the `/auth/callback` route (task 20.2).
 *
 * The token exchange itself (`handleAuthCallback`) is covered in
 * `src/lib/auth.test.ts`; here we inject `runCallback`/`login` and assert the
 * component's routing/UI behavior: navigate to the dashboard on success
 * (Requirement 1.2) and offer to restart sign-in on failure (Requirements 1.3,
 * 1.1).
 *
 * Validates: Requirements 1.1
 */

/**
 * Render AuthCallback inside a router whose "/" route shows a marker, so a
 * successful callback that navigates to `successPath` can be asserted by the
 * marker appearing.
 */
function renderCallback(props: Parameters<typeof AuthCallback>[0]) {
  return render(
    <MemoryRouter initialEntries={["/auth/callback"]}>
      <Routes>
        <Route path="/auth/callback" element={<AuthCallback {...props} />} />
        <Route path="/" element={<div>dashboard landed</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AuthCallback", () => {
  it("navigates to the dashboard after a successful code exchange", async () => {
    const runCallback = vi.fn().mockResolvedValue(undefined);
    const login = vi.fn().mockResolvedValue(undefined);

    renderCallback({ runCallback, login, successPath: "/" });

    // Landed on the success route (Requirement 1.2).
    expect(await screen.findByText("dashboard landed")).toBeInTheDocument();
    expect(runCallback).toHaveBeenCalledTimes(1);
    expect(login).not.toHaveBeenCalled();
  });

  it("shows the completing-sign-in status while the exchange is in flight", () => {
    // A promise that never resolves keeps the component in its pending state.
    const runCallback = vi.fn().mockReturnValue(new Promise<void>(() => {}));

    renderCallback({ runCallback, login: vi.fn(), successPath: "/" });

    expect(screen.getByRole("status")).toHaveTextContent(
      /completing sign in/i,
    );
    expect(screen.queryByText("dashboard landed")).not.toBeInTheDocument();
  });

  it("surfaces an error and restarts sign-in when the exchange fails", async () => {
    const user = userEvent.setup();
    const runCallback = vi
      .fn()
      .mockRejectedValue(new Error("Token exchange failed"));
    const login = vi.fn().mockResolvedValue(undefined);

    renderCallback({ runCallback, login, successPath: "/" });

    // Error surfaced; no navigation to the dashboard (Requirement 1.3).
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/token exchange failed/i);
    expect(screen.queryByText("dashboard landed")).not.toBeInTheDocument();

    // Retry button restarts the Hosted UI sign-in (Requirements 1.3, 1.1).
    const retry = screen.getByRole("button", {
      name: /try signing in again/i,
    });
    await user.click(retry);
    expect(login).toHaveBeenCalledTimes(1);
  });

  it("falls back to a generic message when the failure is not an Error", async () => {
    const runCallback = vi.fn().mockRejectedValue("boom");

    renderCallback({ runCallback, login: vi.fn(), successPath: "/" });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /authentication failed/i,
      );
    });
  });
});
