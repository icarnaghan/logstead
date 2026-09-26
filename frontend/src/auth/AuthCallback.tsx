/**
 * `/auth/callback` route component.
 *
 * Reads the OAuth params from the current URL, runs the code exchange, and on
 * success navigates to the dashboard (Requirement 1.2). On failure it surfaces
 * the provider/exchange error and offers to restart sign-in (Requirement 1.3).
 */

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  handleAuthCallback,
  login as defaultLogin,
  parseCallbackParams,
  type AuthDeps,
} from "../lib/auth";

export interface AuthCallbackProps {
  /** Overridable for tests. */
  runCallback?: (deps?: AuthDeps) => Promise<unknown>;
  /** Overridable for tests. */
  login?: (deps?: AuthDeps) => Promise<void>;
  /** Route to land on after a successful exchange. Defaults to the dashboard. */
  successPath?: string;
}

function defaultRunCallback(): Promise<unknown> {
  const params = parseCallbackParams(window.location.search);
  return handleAuthCallback(params);
}

export default function AuthCallback({
  runCallback = defaultRunCallback,
  login = defaultLogin,
  successPath = "/",
}: AuthCallbackProps) {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  // Guard against React 18/19 StrictMode double-invoke in dev/tests.
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    runCallback()
      .then(() => {
        navigate(successPath, { replace: true });
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Authentication failed");
      });
  }, [navigate, runCallback, successPath]);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 text-fg-muted">
        <p role="alert">Sign-in failed: {error}</p>
        <button
          type="button"
          className="rounded-md bg-accent px-4 py-2 text-accent-fg hover:bg-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          onClick={() => {
            void login();
          }}
        >
          Try signing in again
        </button>
      </div>
    );
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-screen items-center justify-center text-fg-muted"
    >
      Completing sign in…
    </div>
  );
}
