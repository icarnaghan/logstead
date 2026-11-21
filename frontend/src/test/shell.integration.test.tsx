import "./apiStub";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import AppLayout from "../components/AppLayout";
import { ToastProvider } from "../components/ui";
import { useRegisterDirty } from "../lib/navigationGuard";
import { ThemeProvider } from "../theme/ThemeProvider";

/**
 * Shell integration (Requirements 1.4, 6.7, 6.9): the providers wired in
 * `AppLayout` work together. A dirty page blocks a shortcut navigation behind
 * the shared discard confirm, and the palette navigates through the same guard.
 */
function DirtyPage() {
  useRegisterDirty("test-form", true);
  const { pathname } = useLocation();
  return (
    <div>
      <h1 id="page-heading" tabIndex={-1}>
        Dirty page
      </h1>
      <p data-testid="where">{pathname}</p>
    </div>
  );
}

function Other() {
  return (
    <h1 id="page-heading" tabIndex={-1}>
      Other page
    </h1>
  );
}

function renderShell() {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={["/dirty"]}>
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="dirty" element={<DirtyPage />} />
              <Route path="properties" element={<Other />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

describe("shell integration", () => {
  it("asks before leaving a dirty page via a `g p` shortcut, and stays on Keep editing", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.keyboard("gp");
    expect(
      await screen.findByRole("dialog", { name: /discard changes/i }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Keep editing" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId("where")).toHaveTextContent("/dirty");
  });

  it("navigates after Discard when going through the palette", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getByRole("button", { name: "Search" }));
    await screen.findByRole("dialog", { name: "Command palette" });
    await user.keyboard("Properties{Enter}");
    await user.click(await screen.findByRole("button", { name: "Discard" }));
    expect(
      await screen.findByRole("heading", { name: "Other page" }),
    ).toBeInTheDocument();
  });
});
