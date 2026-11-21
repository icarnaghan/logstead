import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useAsyncResource } from "./useAsyncResource";

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (v: T) => void;
  reject: (e: unknown) => void;
}
function deferred<T>(): Deferred<T> {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useAsyncResource", () => {
  it("starts loading, then succeeds with data", async () => {
    const { result } = renderHook(() =>
      useAsyncResource(() => Promise.resolve("a")),
    );
    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(result.current.data).toBe("a");
    expect(result.current.error).toBeNull();
  });

  it("maps failures through describeError and retries with reload", async () => {
    const loader = vi
      .fn<(s: AbortSignal) => Promise<string>>()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce("ok");
    const { result } = renderHook(() =>
      useAsyncResource(loader, {
        describeError: (e) => (e as Error).message,
      }),
    );
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toBe("boom");
    let settled = false;
    act(() => {
      void result.current.reload().then(() => {
        settled = true;
      });
    });
    await waitFor(() => expect(result.current.status).toBe("success"));
    await waitFor(() => expect(settled).toBe(true));
    expect(result.current.data).toBe("ok");
    expect(result.current.error).toBeNull();
  });

  it("keeps prior data while refreshing and after a refresh error", async () => {
    const second = deferred<string>();
    const loader = vi
      .fn<(s: AbortSignal) => Promise<string>>()
      .mockResolvedValueOnce("first")
      .mockReturnValueOnce(second.promise);
    const { result } = renderHook(() => useAsyncResource(loader));
    await waitFor(() => expect(result.current.status).toBe("success"));
    act(() => {
      void result.current.reload();
    });
    expect(result.current.status).toBe("refreshing");
    expect(result.current.data).toBe("first");
    await act(async () => {
      second.reject(new Error("x"));
      await second.promise.catch(() => undefined);
    });
    expect(result.current.status).toBe("error");
    expect(result.current.data).toBe("first");
  });

  it("aborts the in-flight load on unmount and ignores its result", async () => {
    const d = deferred<string>();
    let seen: AbortSignal | undefined;
    const { result, unmount } = renderHook(() =>
      useAsyncResource((signal) => {
        seen = signal;
        return d.promise;
      }),
    );
    unmount();
    expect(seen?.aborted).toBe(true);
    d.resolve("late");
    await d.promise;
    expect(result.current.data).toBeNull();
  });

  it("ignores AbortError rejections", async () => {
    const abort = Object.assign(new Error("aborted"), { name: "AbortError" });
    const { result } = renderHook(() =>
      useAsyncResource(() => Promise.reject(abort)),
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.error).toBeNull();
    expect(result.current.status).toBe("loading");
  });

  it("resetKeys change aborts, clears data and reloads from loading", async () => {
    const signals: AbortSignal[] = [];
    const second = deferred<string>();
    const loader = vi.fn((signal: AbortSignal) => {
      signals.push(signal);
      return signals.length === 1 ? Promise.resolve("p1") : second.promise;
    });
    const { result, rerender } = renderHook(
      ({ id }: { id: string }) =>
        useAsyncResource(loader, { resetKeys: [id] }),
      { initialProps: { id: "1" } },
    );
    await waitFor(() => expect(result.current.data).toBe("p1"));
    rerender({ id: "2" });
    expect(result.current.status).toBe("loading");
    expect(result.current.data).toBeNull();
    await act(async () => {
      second.resolve("p2");
      await second.promise;
    });
    expect(result.current.data).toBe("p2");
  });

  it("deps change keeps data and reports refreshing", async () => {
    const second = deferred<string>();
    const loader = vi
      .fn<(s: AbortSignal) => Promise<string>>()
      .mockResolvedValueOnce("y2023")
      .mockReturnValueOnce(second.promise);
    const { result, rerender } = renderHook(
      ({ year }: { year: number }) =>
        useAsyncResource(loader, { deps: [year] }),
      { initialProps: { year: 2023 } },
    );
    await waitFor(() => expect(result.current.status).toBe("success"));
    rerender({ year: 2024 });
    expect(result.current.status).toBe("refreshing");
    expect(result.current.data).toBe("y2023");
    await act(async () => {
      second.resolve("y2024");
      await second.promise;
    });
    expect(result.current.data).toBe("y2024");
  });

  it("does not load while disabled, and loads once enabled", async () => {
    const loader = vi.fn(() => Promise.resolve("v"));
    const { result, rerender } = renderHook(
      ({ on }: { on: boolean }) => useAsyncResource(loader, { enabled: on }),
      { initialProps: { on: false } },
    );
    expect(result.current.status).toBe("idle");
    expect(loader).not.toHaveBeenCalled();
    rerender({ on: true });
    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it("setData replaces data for optimistic updates", async () => {
    const { result } = renderHook(() =>
      useAsyncResource(() => Promise.resolve([1, 2])),
    );
    await waitFor(() => expect(result.current.status).toBe("success"));
    act(() => result.current.setData((p) => (p ? [...p, 3] : p)));
    expect(result.current.data).toEqual([1, 2, 3]);
  });

  it("an inline loader identity change does not retrigger loading", async () => {
    const calls = vi.fn();
    const { result, rerender } = renderHook(() =>
      useAsyncResource(() => {
        calls();
        return Promise.resolve(1);
      }),
    );
    await waitFor(() => expect(result.current.status).toBe("success"));
    rerender();
    rerender();
    expect(calls).toHaveBeenCalledTimes(1);
  });
});
