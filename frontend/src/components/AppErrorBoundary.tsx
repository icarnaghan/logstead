import { Component, useEffect, useRef, type ErrorInfo, type ReactNode } from "react";
import { cn } from "../lib/cn";
import { Button } from "./ui/Button";

/**
 * Safe, generic fallback shown when rendering throws (review R10).
 *
 * Never renders the error message, stack or component stack: those can leak
 * internals (ids, URLs, API payloads) to the user. Details go to the console
 * in development builds only.
 *
 * Accessibility: `role="alert"` announces the failure, and focus moves to the
 * heading on mount so keyboard and screen-reader users land on it. The `h1`
 * replaces the failed page's own heading (route scope) or is the only heading
 * on the screen (app scope).
 */
export function ErrorFallback({
  onReset,
  scope,
}: {
  onReset: () => void;
  scope: "app" | "route";
}) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, []);
  return (
    <div
      className={cn(
        scope === "app" && "flex min-h-screen items-center justify-center bg-canvas p-4 text-fg",
      )}
    >
      <div
        role="alert"
        className="mx-auto max-w-lg rounded-lg border border-danger bg-danger-subtle p-6 text-center"
      >
        <h1
          ref={headingRef}
          tabIndex={-1}
          className="text-page-title text-fg focus:outline-none"
        >
          Something went wrong
        </h1>
        <p className="mt-2 text-sm text-fg-muted">
          This page hit an unexpected problem. Your data has not been changed.
          Try again, or go back to the dashboard.
        </p>
        <div className="mt-4 flex flex-wrap justify-center gap-3">
          <Button variant="primary" onClick={onReset}>
            Try again
          </Button>
          <Button variant="secondary" asChild>
            {/* Plain anchor: a full load recovers even if router state is broken. */}
            <a href="/">Go to dashboard</a>
          </Button>
        </div>
      </div>
    </div>
  );
}

export interface AppErrorBoundaryProps {
  children: ReactNode;
  /** `app` fills the screen (no shell); `route` renders inside the shell. */
  scope?: "app" | "route";
}

interface State {
  hasError: boolean;
}

/**
 * Catches render errors below it and shows {@link ErrorFallback}. Place one at
 * the app root and one around the route outlet; for the route boundary pass a
 * `key` derived from the location so navigating away resets it.
 */
export class AppErrorBoundary extends Component<AppErrorBoundaryProps, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    if (import.meta.env.DEV) {
      console.error("AppErrorBoundary caught an error", error, info.componentStack);
    }
  }

  private reset = () => this.setState({ hasError: false });

  render(): ReactNode {
    if (this.state.hasError) {
      return <ErrorFallback scope={this.props.scope ?? "app"} onReset={this.reset} />;
    }
    return this.props.children;
  }
}

export default AppErrorBoundary;
