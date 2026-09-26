import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RequireAuth from "./RequireAuth";

/**
 * Component tests for the route guard (task 20.2).
 *
 * These exercise the guard's rendering/redirect behavior in isolation, with
 * the `isAuthenticated` and `login` seams injected. The lib-level PKCE/token
 * flow is covered separately in `src/lib/auth.test.ts`.
 *
 * Validates: Requirements 1.1
 */
describe("RequireAuth", () => {
  it("renders a redirect placeholder and kicks off sign-in when unauthenticated", () => {
    const login = vi.fn().mockResolvedValue(undefined);

    render(
      <RequireAuth isAuthenticated={() => false} login={login}>
        <div>protected content</div>
      </RequireAuth>,
    );

    // Protected content is withheld from an unauthenticated user.
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();

    // A polite status placeholder is shown while the browser redirects.
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent(/redirecting to sign in/i);

    // The Hosted UI redirect was kicked off (Requirement 1.1).
    expect(login).toHaveBeenCalledTimes(1);
  });

  it("renders children and does not redirect when authenticated", () => {
    const login = vi.fn().mockResolvedValue(undefined);

    render(
      <RequireAuth isAuthenticated={() => true} login={login}>
        <div>protected content</div>
      </RequireAuth>,
    );

    expect(screen.getByText("protected content")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(login).not.toHaveBeenCalled();
  });
});
