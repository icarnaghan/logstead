import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ScheduleEImportForm } from "../components/schedule-e-import/ScheduleEImportForm";
import type { EntryState } from "../components/schedule-e-import/PropertyEntryCard";
import { useBeforeUnloadWhen } from "../lib/importsDirty";
import ImportsLayout from "./ImportsLayout";

/**
 * Imports tab guard tests (task 12.2, Requirements 10.8-10.10).
 * Uses the real ImportsLayout, tabs and form.
 */

const MANUAL = "/imports/schedule-e";
const PDF = "/imports/schedule-e/extract";

function Probe() {
  return <div data-testid="pathname">{useLocation().pathname}</div>;
}

const seeded: EntryState = {
  id: "seed-1",
  mapping: "new",
  propertyId: "",
  newPropertyName: "Seeded",
  newPropertyAddress: "1 Main St",
  amounts: { 3: "1000" },
  otherDescription: "",
};

function renderGuard(initialEntries?: EntryState[]) {
  return render(
    <MemoryRouter initialEntries={[MANUAL]}>
      <Probe />
      <Routes>
        <Route path="/imports" element={<ImportsLayout />}>
          <Route
            path="schedule-e"
            element={
              <ScheduleEImportForm
                submit={vi.fn()}
                loadProperties={() => Promise.resolve([])}
                initialTaxYear={initialEntries ? 2023 : undefined}
                initialEntries={initialEntries}
              />
            }
          />
          <Route path="schedule-e/extract" element={<p>PDF page</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

const pathname = () => screen.getByTestId("pathname").textContent;

async function editTaxYear(user: ReturnType<typeof userEvent.setup>) {
  const input = await screen.findByLabelText("Tax year");
  await user.clear(input);
  await user.type(input, "2020");
}

afterEach(() => vi.restoreAllMocks());

describe("Imports tab guard (Req 10.8, 10.9)", () => {
  it("dirty: tab click confirms and stays until confirmed", async () => {
    const user = userEvent.setup();
    renderGuard();
    await editTaxYear(user);

    await user.click(screen.getByRole("link", { name: "Upload PDF" }));
    expect(await screen.findByText("Discard changes?")).toBeInTheDocument();
    expect(pathname()).toBe(MANUAL);

    await user.click(screen.getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(pathname()).toBe(PDF));
    expect(screen.getByText("PDF page")).toBeInTheDocument();
  });

  it("Keep editing retains entries and stays on the tab", async () => {
    const user = userEvent.setup();
    renderGuard();
    await editTaxYear(user);

    await user.click(screen.getByRole("link", { name: "Upload PDF" }));
    await user.click(await screen.findByRole("button", { name: "Keep editing" }));

    await waitFor(() =>
      expect(screen.queryByText("Discard changes?")).not.toBeInTheDocument(),
    );
    expect(pathname()).toBe(MANUAL);
    expect(screen.getByLabelText("Tax year")).toHaveValue(2020);
  });

  it("clean form switches without confirmation", async () => {
    const user = userEvent.setup();
    renderGuard();
    await screen.findByLabelText("Tax year");

    await user.click(screen.getByRole("link", { name: "Upload PDF" }));
    expect(screen.queryByText("Discard changes?")).not.toBeInTheDocument();
    expect(pathname()).toBe(PDF);
  });

  it("extraction-seeded form is clean until edited", async () => {
    const user = userEvent.setup();
    renderGuard([seeded]);
    expect(await screen.findByLabelText("Tax year")).toHaveValue(2023);

    // Untouched: switching is not guarded.
    const addedBefore = window.dispatchEvent(
      new Event("beforeunload", { cancelable: true }),
    );
    expect(addedBefore).toBe(true);

    await editTaxYear(user);
    await user.click(screen.getByRole("link", { name: "Upload PDF" }));
    expect(await screen.findByText("Discard changes?")).toBeInTheDocument();
    expect(pathname()).toBe(MANUAL);
  });

  it("seeded form switches without confirmation when unedited", async () => {
    const user = userEvent.setup();
    renderGuard([seeded]);
    await screen.findByLabelText("Tax year");
    await user.click(screen.getByRole("link", { name: "Upload PDF" }));
    expect(screen.queryByText("Discard changes?")).not.toBeInTheDocument();
    expect(pathname()).toBe(PDF);
  });
});

describe("useBeforeUnloadWhen (Req 10.10)", () => {
  it("adds the listener while dirty and removes it when clean or unmounted", () => {
    const add = vi.spyOn(window, "addEventListener");
    const remove = vi.spyOn(window, "removeEventListener");
    const count = (spy: typeof add) =>
      spy.mock.calls.filter(([type]) => type === "beforeunload").length;

    const { rerender, unmount } = renderHook(
      ({ dirty }) => useBeforeUnloadWhen(dirty),
      { initialProps: { dirty: false } },
    );
    expect(count(add)).toBe(0);

    rerender({ dirty: true });
    expect(count(add)).toBe(1);
    const event = new Event("beforeunload", { cancelable: true });
    act(() => {
      window.dispatchEvent(event);
    });
    expect(event.defaultPrevented).toBe(true);

    rerender({ dirty: false });
    expect(count(remove)).toBe(1);

    rerender({ dirty: true });
    expect(count(add)).toBe(2);
    unmount();
    expect(count(remove)).toBe(2);

    const after = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(after);
    expect(after.defaultPrevented).toBe(false);
  });

  it("layout registers the guard only once the form is dirty", async () => {
    const user = userEvent.setup();
    renderGuard();
    await screen.findByLabelText("Tax year");

    const clean = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);

    await editTaxYear(user);
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
  });
});
