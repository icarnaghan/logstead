import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ExtractionJobView } from "../../api/scheduleEExtraction";
import { useExtractionJob } from "./useExtractionJob";

function view(partial: Partial<ExtractionJobView>): ExtractionJobView {
  return {
    job_id: "job-1",
    status: "processing",
    outcome: null,
    message: null,
    review_draft: null,
    ...partial,
  };
}

/** Tiny harness that renders the hook's state so tests can read it from the DOM. */
function Harness({
  jobId,
  getExtraction,
}: {
  jobId: string | null;
  getExtraction: typeof import("../../api/scheduleEExtraction").getExtraction;
}) {
  const state = useExtractionJob(jobId, { intervalMs: 1000, getExtraction });
  return (
    <div>
      <span data-testid="status">{state.status ?? "none"}</span>
      <span data-testid="outcome">{state.outcome ?? "none"}</span>
      <span data-testid="message">{state.message ?? "none"}</span>
      <span data-testid="columns">
        {state.reviewDraft?.columns.length ?? -1}
      </span>
    </div>
  );
}

/** Flush microtasks so awaited promises inside the hook settle under fake timers. */
async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useExtractionJob — transitions and stop-on-terminal (Req 3)", () => {
  it("polls while processing then stops after reaching complete, making no further calls", async () => {
    const getExtraction = vi
      .fn()
      .mockResolvedValueOnce(view({ status: "processing" }))
      .mockResolvedValueOnce(view({ status: "processing" }))
      .mockResolvedValueOnce(
        view({
          status: "complete",
          outcome: "draft",
          review_draft: {
            tax_year: 2023,
            tax_year_needs_verification: false,
            columns: [
              {
                address_text: "12 Maple St",
                address_confidence: 97,
                suggested_property_id: null,
                suggested_property_name: null,
                mapping_confidence: null,
                lines: [],
              },
            ],
          },
        }),
      );

    render(<Harness jobId="job-1" getExtraction={getExtraction} />);

    // First poll fires immediately on mount.
    await flush();
    expect(screen.getByTestId("status")).toHaveTextContent("processing");
    expect(getExtraction).toHaveBeenCalledTimes(1);

    // Second poll after the interval.
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    await flush();
    expect(getExtraction).toHaveBeenCalledTimes(2);

    // Third poll reaches a terminal state.
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    await flush();
    expect(getExtraction).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId("status")).toHaveTextContent("complete");
    expect(screen.getByTestId("outcome")).toHaveTextContent("draft");
    expect(screen.getByTestId("columns")).toHaveTextContent("1");

    // No further polling once terminal — advancing time makes no new calls.
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    await flush();
    expect(getExtraction).toHaveBeenCalledTimes(3);
  });

  it("stops polling on a failed terminal state and exposes the message", async () => {
    const getExtraction = vi
      .fn()
      .mockResolvedValueOnce(view({ status: "pending" }))
      .mockResolvedValueOnce(
        view({ status: "failed", message: "a valid PDF is required" }),
      );

    render(<Harness jobId="job-1" getExtraction={getExtraction} />);

    await flush();
    expect(screen.getByTestId("status")).toHaveTextContent("pending");

    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    await flush();
    expect(screen.getByTestId("status")).toHaveTextContent("failed");
    expect(screen.getByTestId("message")).toHaveTextContent(
      "a valid PDF is required",
    );
    expect(getExtraction).toHaveBeenCalledTimes(2);

    await act(async () => {
      vi.advanceTimersByTime(10000);
    });
    await flush();
    expect(getExtraction).toHaveBeenCalledTimes(2);
  });

  it("does not poll when jobId is null", async () => {
    const getExtraction = vi.fn().mockResolvedValue(view({}));
    render(<Harness jobId={null} getExtraction={getExtraction} />);

    await flush();
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    await flush();
    expect(getExtraction).not.toHaveBeenCalled();
    expect(screen.getByTestId("status")).toHaveTextContent("none");
  });

  it("aborts the in-flight poll and clears the timer on unmount", async () => {
    const getExtraction = vi.fn(
      async (_jobId: string, signal?: AbortSignal) =>
        new Promise<ExtractionJobView>((_resolve, reject) => {
          signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    );

    const { unmount } = render(
      <Harness jobId="job-1" getExtraction={getExtraction} />,
    );
    await flush();
    expect(getExtraction).toHaveBeenCalledTimes(1);
    const signal = getExtraction.mock.calls[0][1] as AbortSignal;
    expect(signal.aborted).toBe(false);

    unmount();
    expect(signal.aborted).toBe(true);

    // No further polls after unmount.
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    expect(getExtraction).toHaveBeenCalledTimes(1);
  });
});
