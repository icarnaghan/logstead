/**
 * Route guard: renders children only for an authenticated user, otherwise
 * kicks off the Cognito Hosted UI sign-in redirect (Requirement 1.1).
 *
 * Because sign-in is a full-page redirect to Cognito, there is no in-app
 * "login" route to navigate to; the guard calls `login()` and renders a
 * lightweight placeholder while the browser navigates away.
 */

import { useEffect, type ReactNode } from "react";
import { isAuthenticated as defaultIsAuthenticated } from "../lib/session";
import { login as defaultLogin, type AuthDeps } from "../lib/auth";

export interface RequireAuthProps {
  children: ReactNode;
  /** Overridable for tests. */
  isAuthenticated?: () => boolean;
  /** Overridable for tests. */
  login?: (deps?: AuthDeps) => Promise<void>;
}

export default function RequireAuth({
  children,
  isAuthenticated = defaultIsAuthenticated,
  login = defaultLogin,
}: RequireAuthProps) {
  const authed = isAuthenticated();

  useEffect(() => {
    if (!authed) {
      void login();
    }
  }, [authed, login]);

  if (!authed) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex min-h-screen items-center justify-center text-fg-muted"
      >
        Redirecting to sign in…
      </div>
    );
  }

  return <>{children}</>;
}
