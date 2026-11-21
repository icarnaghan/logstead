import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PackageJobView } from "../../api/accountantPackage";
import { usePackageJob } from "./usePackageJob";

function view(partial: Partial<PackageJobView>): PackageJobView {
  return {
    id: "job-1",
    status: "running",
    tax_year: 2024,
    property_ids: [],
    created_at: "2025-01-01T00:00:00Z",
    finished_at: null,
    message: null,
    size_bytes: null,
    sha256: null,
    file_count: null,
    receipt_count: null,
    skipped_receipt_count: null,
    download_url: null,
    download_expires_in_seconds: null,
    ...partial,
  };
}

function makeApi(overrides: Record<string, unknown> = {}) {
  return {
    createPackage: vi.fn(),
    listPackages: vi.fn().mockResolvedValue({ jobs: [] }),
    getPackage: vi.fn(),
    deletePackage: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

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
});

describe("usePackageJob", () => {
  it("polls at the interval after start and stops on a terminal status", async () => {
    const api = makeApi({
      createPackage: vi.fn().mockResolvedValue(view({ status: "queued" })),
      getPackage: vi
        .fn()
        .mockResolvedValueOnce(view({ status: "running" }))
        .mockResolvedValueOnce(view({ status: "complete" })),
    });
    const { result } = renderHook(() => usePackageJob({ api, intervalMs: 1000 }));
    await flush();
    await act(async () => {
      await result.current.start(2024);
    });
    expect(result.current.job?.status).toBe("queued");
    expect(api.getPackage).not.toHaveBeenCalled();

    await advance(1000);
    expect(api.getPackage).toHaveBeenCalledTimes(1);
    expect(result.current.job?.status).toBe("running");

    await advance(1000);
    expect(result.current.job?.status).toBe("complete");

    await advance(5000);
    expect(api.getPackage).toHaveBeenCalledTimes(2);
  });

  it("tolerates two failed polls and stops on the third", async () => {
    const api = makeApi({
      createPackage: vi.fn().mockResolvedValue(view({ status: "queued" })),
      getPackage: vi.fn().mockRejectedValue(new Error("network down")),
    });
    const { result } = renderHook(() => usePackageJob({ api, intervalMs: 1000 }));
    await flush();
    await act(async () => {
      await result.current.start(2024);
    });

    await advance(1000);
    await advance(1000);
    expect(result.current.error).toBeNull();
    await advance(1000);
    expect(api.getPackage).toHaveBeenCalledTimes(3);
    expect(result.current.error).toBe("network down");

    await advance(5000);
    expect(api.getPackage).toHaveBeenCalledTimes(3);
  });

  it("resumes polling an active job from the list on mount", async () => {
    const api = makeApi({
      listPackages: vi
        .fn()
        .mockResolvedValue({ jobs: [view({ status: "running" })] }),
      getPackage: vi.fn().mockResolvedValue(view({ status: "complete" })),
    });
    const { result } = renderHook(() => usePackageJob({ api, intervalMs: 1000 }));
    await flush();
    expect(result.current.job?.status).toBe("running");
    expect(result.current.busy).toBe(false);

    await advance(1000);
    expect(result.current.job?.status).toBe("complete");
  });

  it("shows the latest finished job without polling, and a failed job as an error", async () => {
    const api = makeApi({
      listPackages: vi.fn().mockResolvedValue({
        jobs: [view({ status: "failed", message: "Too many receipts." })],
      }),
    });
    const { result } = renderHook(() => usePackageJob({ api, intervalMs: 1000 }));
    await flush();
    expect(result.current.error).toBe("Too many receipts.");
    await advance(5000);
    expect(api.getPackage).not.toHaveBeenCalled();
  });

  it("stops polling on unmount", async () => {
    const api = makeApi({
      createPackage: vi.fn().mockResolvedValue(view({ status: "queued" })),
      getPackage: vi.fn().mockResolvedValue(view({ status: "running" })),
    });
    const { result, unmount } = renderHook(() =>
      usePackageJob({ api, intervalMs: 1000 }),
    );
    await flush();
    await act(async () => {
      await result.current.start(2024);
    });
    await advance(1000);
    expect(api.getPackage).toHaveBeenCalledTimes(1);
    unmount();
    await advance(5000);
    expect(api.getPackage).toHaveBeenCalledTimes(1);
  });

  it("refresh reloads the job and remove clears it", async () => {
    const api = makeApi({
      listPackages: vi.fn().mockResolvedValue({
        jobs: [view({ status: "complete", download_url: "https://old" })],
      }),
      getPackage: vi
        .fn()
        .mockResolvedValue(
          view({ status: "complete", download_url: "https://new" }),
        ),
    });
    const { result } = renderHook(() => usePackageJob({ api, intervalMs: 1000 }));
    await flush();
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.job?.download_url).toBe("https://new");

    await act(async () => {
      await result.current.remove();
    });
    expect(api.deletePackage).toHaveBeenCalledWith("job-1");
    expect(result.current.job).toBeNull();
  });

  it("surfaces a create failure message", async () => {
    const api = makeApi({
      createPackage: vi.fn().mockRejectedValue(new Error("Already preparing 2023.")),
    });
    const { result } = renderHook(() => usePackageJob({ api, intervalMs: 1000 }));
    await flush();
    await act(async () => {
      await result.current.start(2024);
    });
    expect(result.current.error).toBe("Already preparing 2023.");
    expect(result.current.busy).toBe(false);
  });
});
