import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AppLayout from "./AppLayout";
import { ToastProvider } from "./ui";
import { ThemeProvider } from "../theme/ThemeProvider";
import * as auth from "../lib/auth";
import { checklistKeys } from "../lib/checklistStorage";
import { setupKeys } from "../lib/onboardingStorage";
import { useSetupGuide } from "../lib/setupGuide";

/** "Show setup guide" wiring in the shell (Requirements 26.3, 26.4). */
function Dashboard() {
  const guide = useSetupGuide();
  const dismissed = window.localStorage.getItem(checklistKeys("u1").dismissed) === "1";
  return (
    <>
      <h1>Dashboard</h1>
      <h2 id="checklist-heading" tabIndex={-1}>
        Setup guide {guide?.resetSignal}
        {dismissed ? " (dismissed)" : ""}
      </h2>
    </>
  );
}

function renderShell(path = "/profile") {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<Dashboard />} />
              <Route path="profile" element={<h1>Profile</h1>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.spyOn(auth, "getUserProfile").mockReturnValue({ sub: "u1", displayName: "u1" });
});

describe("AppLayout — Show setup guide", () => {
  it("menu item clears the stored state, navigates to / and focuses the heading", async () => {
    const user = userEvent.setup();
    const keys = setupKeys("u1");
    window.localStorage.setItem(keys.dismissed, "1");
    window.localStorage.setItem(keys.collapsed, "1");
    renderShell();

    await user.click(screen.getByRole("button", { name: /account menu/i }));
    await user.click(screen.getByRole("menuitem", { name: "Show setup guide" }));

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(window.localStorage.getItem(keys.dismissed)).toBeNull();
    expect(window.localStorage.getItem(keys.collapsed)).toBeNull();
    await waitFor(() =>
      expect(document.getElementById("checklist-heading")).toHaveFocus(),
    );
  });

  it("palette action also works when everything was done and dismissed, from /", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(setupKeys("u1").dismissed, "1");
    renderShell("/");

    await user.keyboard("{Control>}k{/Control}");
    await user.keyboard("setup guide{Enter}");

    await waitFor(() =>
      expect(document.getElementById("checklist-heading")).toHaveFocus(),
    );
    expect(window.localStorage.getItem(setupKeys("u1").dismissed)).toBeNull();
    expect(document.getElementById("checklist-heading")).toHaveTextContent("Setup guide 1");
  });
});
