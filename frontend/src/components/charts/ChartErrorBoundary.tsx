import { Component, type ReactNode } from "react";

/**
 * Minimal error boundary for the chart region (Requirement 14, Error Handling).
 *
 * A chart is only the *visual* representation of data that is always also
 * present as a table. If the lazy chart chunk fails to load, or a chart throws
 * while rendering, the data must never be gated by that failure. This boundary
 * catches render/lazy-load errors from its children and renders the supplied
 * `fallback` instead (in practice: the always-present data table plus a small
 * "chart unavailable" note) so the page degrades gracefully rather than
 * crashing.
 *
 * Kept deliberately small: a class component is the only way to implement
 * `componentDidCatch` / `getDerivedStateFromError` in React.
 */
export interface ChartErrorBoundaryProps {
  /** Rendered in place of the children when a render/lazy error is caught. */
  fallback: ReactNode;
  /** The chart subtree to guard (typically a `Suspense` + lazy chart). */
  children: ReactNode;
}

interface ChartErrorBoundaryState {
  hasError: boolean;
}

export class ChartErrorBoundary extends Component<
  ChartErrorBoundaryProps,
  ChartErrorBoundaryState
> {
  state: ChartErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ChartErrorBoundaryState {
    return { hasError: true };
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return this.props.fallback;
    }
    return this.props.children;
  }
}
