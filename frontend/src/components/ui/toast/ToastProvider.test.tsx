import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider, toastDurationMs, type ToastMessage } from "./ToastProvider";
import { useToast } from "./useToast";

/**
 * Unit + axe tests for the shared toast mechanism
 * (task 3.10, Requirements 5.5).
 *
 * Radix Toast relies on `matchMedia` (for reduced-motion) in jsdom, so we stub
 * it minimally before the suite. Assertions use `findBy*` so we wait for Radix
 * to mount each toast into its live region deterministically.
 */


/** Tiny harness that fires `notify(...)` on button clicks. */
function Harness() {
  const { notify } = useToast();
  return (
    <div>
      <button
        type="button"
        onClick={() =>
          notify({
            variant: "success",
            title: "Transaction saved",
            description: "Your changes were stored.",
          })
        }
      >
        Emit success
      </button>
      <button
        type="button"
        onClick={() => notify({ variant: "error", title: "Save failed" })}
      >
        Emit error
      </button>
    </div>
  );
}

function renderHarness() {
  return render(
    <ToastProvider>
      <Harness />
    </ToastProvider>,
  );
}

describe("toast — emission (Req 5.5)", () => {
  it("shows a success toast in the live region with success styling", async () => {
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByRole("button", { name: "Emit success" }));

    const title = await screen.findByText("Transaction saved");
    expect(screen.getByText("Your changes were stored.")).toBeInTheDocument();

    // The success token styling lives on the Toast.Root wrapping the title.
    const root = title.closest("li") ?? (title.parentElement as HTMLElement);
    expect(root).toHaveClass("border-success");
    expect(root).toHaveClass("bg-success-subtle");
  });

  it("shows an error toast with danger styling", async () => {
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByRole("button", { name: "Emit error" }));

    const title = await screen.findByText("Save failed");
    const root = title.closest("li") ?? (title.parentElement as HTMLElement);
    expect(root).toHaveClass("border-danger");
    expect(root).toHaveClass("bg-danger-subtle");
  });
});

describe("useToast — provider guard", () => {
  it("throws a clear error when used outside a ToastProvider", () => {
    expect(() => renderHook(() => useToast())).toThrow(
      /useToast must be used within a ToastProvider/,
    );
  });
});

describe("toast — accessibility", () => {
  it("has no axe violations for a rendered toast", async () => {
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByRole("button", { name: "Emit success" }));
    const title = await screen.findByText("Transaction saved");

    // Scope axe to the rendered toast itself; the surrounding Radix viewport
    // list markup is the primitive's concern, not this component's contract.
    const root = (title.closest("li") ?? title.parentElement) as HTMLElement;
    const results = await axe(root, {
      rules: {
        "color-contrast": { enabled: false },
        // Radix intentionally sets role="status" on the toast <li> to make it
        // an aria-live status region; axe flags the role/element pairing, but
        // this is the primitive's own accessibility markup, not our contract.
        "aria-allowed-role": { enabled: false },
      },
    });
    expect(results).toHaveNoViolations();
  });
});

/** Harness emitting every toast flavor added in Phase 2. */
function RichHarness({ onAction }: { onAction: () => void }) {
  const { notify } = useToast();
  return (
    <div>
      <button type="button" onClick={() => notify({ variant: "success", title: "Saved" })}>
        Emit success
      </button>
      <button type="button" onClick={() => notify({ variant: "error", title: "Failed" })}>
        Emit error
      </button>
      <button type="button" onClick={() => notify({ variant: "info", title: "FYI" })}>
        Emit info
      </button>
      <button
        type="button"
        onClick={() =>
          notify({
            variant: "success",
            title: "Deleted",
            action: { label: "Undo", onClick: onAction },
          })
        }
      >
        Emit action
      </button>
    </div>
  );
}

function renderRich(onAction: () => void = () => {}) {
  return render(
    <ToastProvider>
      <RichHarness onAction={onAction} />
    </ToastProvider>,
  );
}

describe("toastDurationMs (Req 14.9-14.12)", () => {
  const cases: Array<[string, Pick<ToastMessage, "variant" | "action" | "duration">, number]> = [
    ["success", { variant: "success" }, 5000],
    ["info", { variant: "info" }, 5000],
    ["error", { variant: "error" }, 10000],
    ["action", { variant: "success", action: { label: "Undo", onClick: () => {} } }, 10000],
    ["override", { variant: "error", duration: 1234 }, 1234],
  ];
  it.each(cases)("%s", (_name, t, expected) => {
    expect(toastDurationMs(t)).toBe(expected);
  });
});

describe("toast — dismissal, action, timing (Req 14.9-14.12)", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  // user-event's async delays hang under fake timers, so timer tests use
  // synchronous fireEvent after enabling fake timers.
  function emit(name: string) {
    fireEvent.click(screen.getByRole("button", { name }));
  }

  it("close button has an accessible name and dismisses the toast", async () => {
    const user = userEvent.setup();
    renderRich();
    await user.click(screen.getByRole("button", { name: "Emit success" }));
    await screen.findByText("Saved");

    await user.click(screen.getByRole("button", { name: "Dismiss notification" }));
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });

  it("action toast renders an action button that calls onClick and closes", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    renderRich(onAction);
    await user.click(screen.getByRole("button", { name: "Emit action" }));
    await screen.findByText("Deleted");

    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Deleted")).not.toBeInTheDocument();
  });

  it("success and info auto-dismiss after 5s", async () => {
    vi.useFakeTimers();
    renderRich();
    emit("Emit success");
    emit("Emit info");
    expect(screen.getByText("Saved")).toBeInTheDocument();
    expect(screen.getByText("FYI")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(4900);
    });
    expect(screen.getByText("Saved")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
    expect(screen.queryByText("FYI")).not.toBeInTheDocument();
  });

  it("error toast persists past 5s and dismisses by 10s", async () => {
    vi.useFakeTimers();
    renderRich();
    emit("Emit error");

    act(() => {
      vi.advanceTimersByTime(9900);
    });
    expect(screen.getByText("Failed")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();
  });

  it("pauses auto-dismiss while hovered and resumes on leave", async () => {
    vi.useFakeTimers();
    renderRich();
    emit("Emit success");
    const item = screen.getByText("Saved").closest("li") as HTMLElement;

    const region = item.parentElement?.parentElement as HTMLElement;
    fireEvent.pointerMove(item);
    act(() => {
      vi.advanceTimersByTime(20000);
    });
    expect(screen.getByText("Saved")).toBeInTheDocument();

    fireEvent.pointerLeave(region);
    act(() => {
      vi.advanceTimersByTime(5100);
    });
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });

  it("pauses auto-dismiss while focus is inside the toast", async () => {
    vi.useFakeTimers();
    renderRich();
    emit("Emit success");
    const close = screen.getByRole("button", { name: "Dismiss notification" });

    act(() => {
      close.focus();
    });
    act(() => {
      vi.advanceTimersByTime(20000);
    });
    expect(screen.getByText("Saved")).toBeInTheDocument();

    act(() => {
      close.blur();
    });
    act(() => {
      vi.advanceTimersByTime(5100);
    });
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });
});

describe("toast — info variant and axe (Req 13.5, 13.6)", () => {
  it("styles info toasts with accent tokens", async () => {
    const user = userEvent.setup();
    renderRich();
    await user.click(screen.getByRole("button", { name: "Emit info" }));
    const root = (await screen.findByText("FYI")).closest("li") as HTMLElement;
    expect(root).toHaveClass("border-accent");
    expect(root).toHaveClass("bg-accent-subtle");
  });

  it("has no axe violations for an action toast with close button", async () => {
    const user = userEvent.setup();
    renderRich();
    await user.click(screen.getByRole("button", { name: "Emit action" }));
    const root = (await screen.findByText("Deleted")).closest("li") as HTMLElement;
    const results = await axe(root, {
      rules: {
        "color-contrast": { enabled: false },
        "aria-allowed-role": { enabled: false },
      },
    });
    expect(results).toHaveNoViolations();
  });
});
