import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChartErrorBoundary } from "./ChartErrorBoundary";

/**
 * Unit tests for the chart error boundary (task 15.8, Requirement 14 error
 * handling). A chart failure must never gate the data: a throwing child falls
 * back to the supplied fallback (in practice the always-present data table).
 */

function Boom(): never {
  throw new Error("chart chunk failed");
}

describe("ChartErrorBoundary", () => {
  it("renders children when they do not throw", () => {
    render(
      <ChartErrorBoundary fallback={<div>fallback table</div>}>
        <div>the chart</div>
      </ChartErrorBoundary>,
    );
    expect(screen.getByText("the chart")).toBeInTheDocument();
    expect(screen.queryByText("fallback table")).not.toBeInTheDocument();
  });

  it("renders the fallback when a child throws during render", () => {
    // React logs the caught error to console.error; silence it for a clean run.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      render(
        <ChartErrorBoundary
          fallback={<div>chart unavailable — showing data table</div>}
        >
          <Boom />
        </ChartErrorBoundary>,
      );
      expect(
        screen.getByText("chart unavailable — showing data table"),
      ).toBeInTheDocument();
    } finally {
      spy.mockRestore();
    }
  });
});
