import { render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { beforeAll, describe, expect, it } from "vitest";
import { ToastProvider } from "./ToastProvider";
import { useToast } from "./useToast";

/**
 * Unit + axe tests for the shared toast mechanism
 * (task 3.10, Requirements 5.5).
 *
 * Radix Toast relies on `matchMedia` (for reduced-motion) in jsdom, so we stub
 * it minimally before the suite. Assertions use `findBy*` so we wait for Radix
 * to mount each toast into its live region deterministically.
 */

beforeAll(() => {
  if (!window.matchMedia) {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      }),
    });
  }
});

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
