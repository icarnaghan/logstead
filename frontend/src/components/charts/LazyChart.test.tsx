import { lazy } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LazyChart } from "./LazyChart";

/**
 * Unit tests for the reusable lazy-loading composition (task 15.8,
 * Requirements 14.1–14.3). LazyChart composes an error boundary (fallback =
 * data table) around a Suspense boundary (fallback = ChartPlaceholder) around
 * the lazy chart node.
 */

describe("LazyChart", () => {
  it("renders children normally when nothing is pending or failing", () => {
    render(
      <LazyChart fallbackTable={<div>fallback table</div>} height={280}>
        <div>rendered chart</div>
      </LazyChart>,
    );
    expect(screen.getByText("rendered chart")).toBeInTheDocument();
    // No loading placeholder and no fallback table when the child renders.
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText("fallback table")).not.toBeInTheDocument();
  });

  it("shows the ChartPlaceholder (role=status) while a lazy child is pending", () => {
    // A lazy component whose import promise never resolves within the test tick,
    // so Suspense stays in its fallback state (Req 14.3).
    const PendingChart = lazy(
      () =>
        new Promise<{ default: React.ComponentType }>(() => {
          /* never resolves */
        }),
    );

    render(
      <LazyChart fallbackTable={<div>fallback table</div>} height={280}>
        <PendingChart />
      </LazyChart>,
    );

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Loading chart…");
    expect(screen.queryByText("fallback table")).not.toBeInTheDocument();
  });

  it("falls back to the data table when the child throws", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    function Boom(): never {
      throw new Error("chart failed to render");
    }
    try {
      render(
        <LazyChart
          fallbackTable={<div>chart unavailable — showing data table</div>}
          height={280}
        >
          <Boom />
        </LazyChart>,
      );
      expect(
        screen.getByText("chart unavailable — showing data table"),
      ).toBeInTheDocument();
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    } finally {
      spy.mockRestore();
    }
  });
});
