import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { axe } from "vitest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Property } from "../api/properties";
import { listProperties } from "../api/properties";
import { ThemeProvider } from "../theme/ThemeProvider";
import AppLayout from "./AppLayout";
import { PropertySwitcher } from "./PropertySwitcher";
import {
  ShellPropertiesProvider,
  useShellProperties,
} from "./ShellPropertiesContext";

vi.mock("../api/properties", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/properties")>();
  return { ...actual, listProperties: vi.fn() };
});

function prop(id: string, name: string): Property {
  return { id, user_id: "u1", name, address_text: `${name} St` };
}

const A = prop("a-1", "Alpha House");
const B = prop("b-2", "Beta Cabin");

function Where() {
  const { pathname, search } = useLocation();
  return <div data-testid="where">{pathname + search}</div>;
}

function Reloader() {
  const { reload } = useShellProperties();
  return <button onClick={reload}>reload</button>;
}

function renderSwitcher(
  load: (signal?: AbortSignal) => Promise<Property[]>,
  path = "/",
) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ShellPropertiesProvider load={load}>
        <PropertySwitcher />
        <Reloader />
        <Where />
      </ShellPropertiesProvider>
    </MemoryRouter>,
  );
}

const resolved = (list: Property[]) => () => Promise.resolve(list);

describe("PropertySwitcher (Req 19)", () => {
  it("has the accessible name 'Switch property' and lists properties", async () => {
    renderSwitcher(resolved([A, B]), "/properties/a-1");
    const select = await screen.findByRole("combobox", {
      name: "Switch property",
    });
    const options = within(select).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      "Alpha House",
      "Beta Cabin",
    ]);
  });

  it("selects the current property on property routes", async () => {
    renderSwitcher(resolved([A, B]), "/properties/b-2/loans");
    const select = await screen.findByRole("combobox");
    expect(select).toHaveValue("b-2");
  });

  it("shows a placeholder on non-property routes", async () => {
    renderSwitcher(resolved([A, B]), "/");
    const select = await screen.findByRole("combobox");
    expect(select).toHaveValue("");
    expect(
      within(select).getByRole("option", { name: "Switch property" }),
    ).toBeDisabled();
  });

  it("navigates to the same section and keeps the year param", async () => {
    const user = userEvent.setup();
    renderSwitcher(resolved([A, B]), "/properties/a-1/loans?year=2023&x=1");
    await user.selectOptions(await screen.findByRole("combobox"), "b-2");
    expect(screen.getByTestId("where")).toHaveTextContent(
      "/properties/b-2/loans?year=2023",
    );
  });

  it("goes to the overview from a non-property route", async () => {
    const user = userEvent.setup();
    renderSwitcher(resolved([A, B]), "/dashboard");
    await user.selectOptions(await screen.findByRole("combobox"), "a-1");
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/properties\/a-1$/);
  });

  it("is keyboard operable", async () => {
    const user = userEvent.setup();
    renderSwitcher(resolved([A, B]), "/properties/a-1");
    const select = await screen.findByRole("combobox");
    await user.tab();
    expect(select).toHaveFocus();
    // jsdom does not implement native arrow-key option changes, so commit the
    // choice through the focused select.
    await user.selectOptions(select, "b-2");
    expect(select).toHaveFocus();
    expect(screen.getByTestId("where")).toHaveTextContent("/properties/b-2");
  });

  it("shows a skeleton while loading, without a select", () => {
    const { container } = renderSwitcher(() => new Promise(() => {}));
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(container.querySelector(".h-9.w-40")).not.toBeNull();
  });

  it("renders nothing on error", async () => {
    const { container } = renderSwitcher(() => Promise.reject(new Error("x")));
    await waitFor(() =>
      expect(container.querySelector(".h-9.w-40")).toBeNull(),
    );
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("renders nothing with zero properties", async () => {
    const { container } = renderSwitcher(resolved([]));
    await waitFor(() =>
      expect(container.querySelector(".h-9.w-40")).toBeNull(),
    );
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("stays populated and updates after a refresh", async () => {
    const user = userEvent.setup();
    const load = vi
      .fn<(s?: AbortSignal) => Promise<Property[]>>()
      .mockResolvedValueOnce([A])
      .mockResolvedValueOnce([A, B]);
    renderSwitcher(load);
    const select = await screen.findByRole("combobox");
    expect(within(select).getAllByRole("option")).toHaveLength(2); // placeholder + A
    await user.click(screen.getByRole("button", { name: "reload" }));
    expect(screen.getByRole("combobox")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        within(screen.getByRole("combobox")).getByRole("option", {
          name: "Beta Cabin",
        }),
      ).toBeInTheDocument(),
    );
  });

  it("keeps the list when a refresh fails", async () => {
    const user = userEvent.setup();
    const load = vi
      .fn<(s?: AbortSignal) => Promise<Property[]>>()
      .mockResolvedValueOnce([A, B])
      .mockRejectedValueOnce(new Error("boom"));
    renderSwitcher(load);
    await screen.findByRole("combobox");
    await user.click(screen.getByRole("button", { name: "reload" }));
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    await act(async () => {});
    const select = screen.getByRole("combobox");
    expect(
      within(select).getByRole("option", { name: "Beta Cabin" }),
    ).toBeInTheDocument();
  });

  it("has no axe violations", async () => {
    const { container } = renderSwitcher(resolved([A, B]), "/properties/a-1");
    await screen.findByRole("combobox");
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("PropertySwitcher in AppLayout (Req 19.1, 19.2)", () => {
  beforeEach(() => {
    vi.mocked(listProperties).mockResolvedValue([A, B]);
  });

  it("renders a drawer copy (sm:hidden) and a header copy (hidden sm:block)", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/properties/a-1"]}>
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="*" element={<div>page</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>,
    );

    const header = screen.getByRole("banner");
    const headerSelect = await within(header).findByRole("combobox", {
      name: "Switch property",
    });
    expect(headerSelect.closest("div")!.className).toContain("hidden");
    expect(headerSelect.closest("div")!.className).toContain("sm:block");

    await user.click(
      screen.getByRole("button", { name: /open navigation menu/i }),
    );
    const dialog = await screen.findByRole("dialog");
    const drawerSelect = await within(dialog).findByRole("combobox", {
      name: "Switch property",
    });
    expect(drawerSelect.closest("div")!.className).toContain("sm:hidden");
    expect(drawerSelect).toHaveValue("a-1");
  });
});
