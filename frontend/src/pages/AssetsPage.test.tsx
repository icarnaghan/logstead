import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import AssetsPage, { type AssetsApi } from "./AssetsPage";
import { ApiError } from "../lib/apiClient";
import { ToastProvider } from "../components/ui";
import { ThemeProvider } from "../theme/ThemeProvider";
import type { DepreciableAsset, ScheduleRow } from "../api/assets";


/**
 * Component tests for the depreciable-assets page (task 23.1, Requirements 8 & 9).
 *
 * The assets API is fully mocked, so these tests exercise the UI behaviour
 * (list rendering, the 27.5-year recovery-period default, the cost_basis field
 * error, and schedule display) without any network access.
 */

function asset(overrides: Partial<DepreciableAsset> = {}): DepreciableAsset {
  return {
    id: "asset-1",
    description: "Rental building",
    cost_basis: "275000.00",
    placed_in_service_date: "2023-06-15",
    recovery_period_years: 27.5,
    created_at: "2023-06-15T00:00:00Z",
    updated_at: "2023-06-15T00:00:00Z",
    ...overrides,
  };
}

// Scope schedule queries to the schedule table (the asset list is also a table).
const SCHEDULE_TABLE = { name: /year-by-year depreciation schedule/i };
const scheduleTable = () =>
  screen.findByRole("table", SCHEDULE_TABLE).then((t) => within(t));

function makeApi(overrides: Partial<AssetsApi> = {}): AssetsApi {
  return {
    listAssets: vi.fn().mockResolvedValue([]),
    createAsset: vi.fn().mockResolvedValue(asset()),
    updateAsset: vi.fn().mockResolvedValue(asset()),
    deleteAsset: vi.fn().mockResolvedValue(undefined),
    getSchedule: vi.fn().mockResolvedValue([]),
    ...overrides,
  };
}

function renderPage(api: AssetsApi, search = "") {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={[`/properties/prop-1/assets${search}`]}>
          <Routes>
            <Route
              path="/properties/:propertyId/assets"
              element={<AssetsPage api={api} />}
            />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

describe("AssetsPage — listing (Req 8.7)", () => {
  it("renders the property's assets in a table", async () => {
    const api = makeApi({
      listAssets: vi
        .fn()
        .mockResolvedValue([
          asset({ id: "a1", description: "Roof replacement" }),
          asset({ id: "a2", description: "HVAC unit" }),
        ]),
    });

    renderPage(api);

    const table = await screen.findByRole("table");
    await within(table).findByText("Roof replacement");
    expect(within(table).getByText("Roof replacement")).toBeInTheDocument();
    expect(within(table).getByText("HVAC unit")).toBeInTheDocument();
    expect(api.listAssets).toHaveBeenCalledWith("prop-1");
  });

  it("shows an empty state with an Add asset action and no 'form above' copy (Req 1.2, 1.6)", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);
    expect(
      await screen.findByRole("heading", { name: /no assets yet/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/form above/i)).not.toBeInTheDocument();

    // The empty state is the only Add trigger (no header button), and no form is
    // rendered until it is used.
    const adds = screen.getAllByRole("button", { name: /add asset/i });
    expect(adds).toHaveLength(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/description/i)).not.toBeInTheDocument();

    await user.click(adds[0]);
    expect(
      await screen.findByRole("dialog", { name: "Add asset" }),
    ).toBeInTheDocument();
  });

  it("shows the table plus an Add asset button, and no form while closed (Req 1.3, 1.4)", async () => {
    const api = makeApi({
      listAssets: vi.fn().mockResolvedValue([asset()]),
    });
    renderPage(api);
    await screen.findAllByText("Rental building");
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add asset" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/cost basis/i)).not.toBeInTheDocument();
  });

  it("hides the Add asset button while loading and on a load error (Req 1.5)", async () => {
    let reject: (e: Error) => void = () => {};
    const api = makeApi({
      listAssets: vi.fn().mockImplementation(
        () =>
          new Promise<DepreciableAsset[]>((_res, rej) => {
            reject = rej;
          }),
      ),
    });
    renderPage(api);
    await screen.findByRole("status");
    expect(
      screen.queryByRole("button", { name: /add asset/i }),
    ).not.toBeInTheDocument();

    reject(new Error("boom"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /unable to load depreciable assets/i,
    );
    expect(
      screen.queryByRole("button", { name: /add asset/i }),
    ).not.toBeInTheDocument();
  });

  it("shows a role=status loading state while assets are fetching", async () => {
    let resolve: (rows: DepreciableAsset[]) => void = () => {};
    const api = makeApi({
      listAssets: vi.fn().mockImplementation(
        () =>
          new Promise<DepreciableAsset[]>((r) => {
            resolve = r;
          }),
      ),
    });
    renderPage(api);

    expect(await screen.findByRole("status")).toHaveAccessibleName(
      /loading assets/i,
    );

    resolve([]);
    await screen.findByRole("heading", { name: /no assets yet/i });
  });
});

/** Opens the Add modal from the empty state and returns the dialog element. */
async function openAddFromEmpty(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText(/no assets yet/i);
  await user.click(screen.getByRole("button", { name: /add asset/i }));
  return screen.findByRole("dialog", { name: "Add asset" });
}

async function fillAsset(
  user: ReturnType<typeof userEvent.setup>,
  dialog: HTMLElement,
  values: { description: string; cost: string; date: string },
) {
  await user.type(
    within(dialog).getByLabelText(/description/i),
    values.description,
  );
  await user.type(within(dialog).getByLabelText(/cost basis/i), values.cost);
  await user.type(
    within(dialog).getByLabelText(/placed in service/i),
    values.date,
  );
}

describe("AssetsPage — create with recovery-period default (Req 8.1, 8.4)", () => {
  it("defaults recovery period to 27.5 when the field is left blank", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);

    const dialog = await openAddFromEmpty(user);
    await fillAsset(user, dialog, {
      description: "New roof",
      cost: "12000.00",
      date: "2024-03-10",
    });
    // Deliberately leave "Recovery period" blank.

    await user.click(within(dialog).getByRole("button", { name: /add asset/i }));

    expect(api.createAsset).toHaveBeenCalledWith("prop-1", {
      description: "New roof",
      cost_basis: "12000.00",
      placed_in_service_date: "2024-03-10",
      recovery_period_years: 27.5,
    });
  });

  it("communicates the 27.5-year default to the user", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);
    await openAddFromEmpty(user);

    expect(screen.getByText(/default of 27\.5 years/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/recovery period/i)).toHaveAttribute(
      "placeholder",
      "27.5",
    );
  });
});

describe("AssetsPage — cost_basis validation (Req 8.2)", () => {
  it("surfaces the backend field error for cost_basis <= 0", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      createAsset: vi
        .fn()
        .mockRejectedValue(
          new ApiError(400, "cost_basis must be greater than 0", {
            field: "cost_basis",
            message: "cost_basis must be greater than 0",
          }),
        ),
    });

    renderPage(api);
    const dialog = await openAddFromEmpty(user);

    await fillAsset(user, dialog, {
      description: "Bad asset",
      cost: "0",
      date: "2024-01-01",
    });
    await user.click(within(dialog).getByRole("button", { name: /add asset/i }));

    const alerts = await screen.findAllByText(
      /cost_basis must be greater than 0/i,
    );
    expect(alerts.length).toBeGreaterThan(0);

    // The cost-basis input is marked invalid.
    expect(screen.getByLabelText(/cost basis/i)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });
});

describe("AssetsPage — undoable delete + feedback (Req 13)", () => {
  it("deletes immediately without a confirmation, calls the API, refreshes, and toasts success", async () => {
    const user = userEvent.setup();
    const listAssets = vi
      .fn()
      .mockResolvedValueOnce([asset({ id: "a1", description: "Old roof" })])
      .mockResolvedValue([]);
    const api = makeApi({ listAssets });

    renderPage(api);
    await screen.findAllByText("Old roof");

    await user.click(
      within(screen.getByRole("table")).getByRole("button", {
        name: /delete/i,
      }),
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(api.deleteAsset).toHaveBeenCalled());
    expect(api.deleteAsset).toHaveBeenCalledWith("prop-1", "a1");
    // The list re-fetches after the delete.
    await screen.findByText(/no assets yet/i);
    // Success toast is announced.
    expect(await screen.findByText("Asset deleted")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("Undo re-creates the asset with the retained data and refreshes", async () => {
    const user = userEvent.setup();
    const a = asset({ id: "a1", description: "Old roof" });
    const listAssets = vi
      .fn()
      .mockResolvedValueOnce([a])
      .mockResolvedValueOnce([])
      .mockResolvedValue([a]);
    const api = makeApi({ listAssets });

    renderPage(api);
    await screen.findAllByText("Old roof");
    await user.click(
      within(screen.getByRole("table")).getByRole("button", {
        name: /delete/i,
      }),
    );
    await user.click(await screen.findByRole("button", { name: "Undo" }));

    await waitFor(() =>
      expect(api.createAsset).toHaveBeenCalledWith(
        "prop-1",
        expect.objectContaining({
          description: "Old roof",
          cost_basis: a.cost_basis,
        }),
      ),
    );
    expect(await screen.findByText("Asset restored")).toBeInTheDocument();
  });
});

describe("AssetsPage — schedule display (Req 9.4)", () => {
  it("renders the schedule rows in a table when an asset is expanded", async () => {
    const user = userEvent.setup();
    const rows: ScheduleRow[] = [
      {
        tax_year: 2023,
        amount: "5833.33",
        remaining_basis: "269166.67",
        method: "straight-line",
        convention: "mid-month",
      },
      {
        tax_year: 2024,
        amount: "10000.00",
        remaining_basis: "259166.67",
        method: "straight-line",
        convention: "mid-month",
      },
    ];
    const api = makeApi({
      listAssets: vi.fn().mockResolvedValue([asset({ id: "a1" })]),
      getSchedule: vi.fn().mockResolvedValue(rows),
    });

    renderPage(api);
    await user.click(
      await screen.findByRole("button", { name: /view schedule/i }),
    );

    // The schedule table appears with year / amount / remaining-basis rows.
    const tables = await screen.findAllByRole("table");
    // The last table is the schedule (the first is the asset list).
    const scheduleTable = tables[tables.length - 1];
    expect(within(scheduleTable).getByText("2023")).toBeInTheDocument();
    // The depreciation schedule is a tax-oriented surface, so amounts render
    // rounded to the nearest whole dollar (Req 11.2): 5833.33 -> $5,833 and
    // 269166.67 -> $269,167. The display rounds at the boundary only; the
    // underlying money strings stay at exact cent precision.
    expect(within(scheduleTable).getByText("$5,833")).toBeInTheDocument();
    expect(within(scheduleTable).getByText("$269,167")).toBeInTheDocument();
    expect(within(scheduleTable).getByText("2024")).toBeInTheDocument();

    expect(api.getSchedule).toHaveBeenCalledWith("prop-1", "a1");
  });
});

// Feature: depreciation-override-and-whole-dollar-display, Req 6.2, 6.3, 6.4
//
// Override persistence from the expanded schedule. Expanding an asset shows the
// editable schedule table; entering an override and submitting it calls the
// injected `updateAsset` with a `depreciation_overrides` map including the new
// year, then reloads the asset list and the schedule without a full page
// reload (Req 6.2, 6.3). A 400 whose field is `depreciation_overrides.<year>`
// surfaces inline next to that year's control and does not present the override
// as saved (Req 6.4).
describe("AssetsPage — override persistence (Req 6.2, 6.3, 6.4)", () => {
  const scheduleRows: ScheduleRow[] = [
    {
      tax_year: 2023,
      amount: "5833.33",
      remaining_basis: "269166.67",
      method: "straight-line",
      convention: "mid-month",
    },
    {
      tax_year: 2024,
      amount: "10000.00",
      remaining_basis: "259166.67",
      method: "straight-line",
      convention: "mid-month",
    },
  ];

  async function expandSchedule(api: AssetsApi) {
    const user = userEvent.setup();
    renderPage(api);
    await screen.findAllByText("Rental building");
    await user.click(
      within(screen.getByRole("table")).getByRole("button", {
        name: /view schedule/i,
      }),
    );
    // Wait for the editable schedule (its override inputs) to render.
    await (await scheduleTable()).findByLabelText("Depreciation override for 2023");
    return user;
  }

  it("submits an override via updateAsset with the new year, then reloads the schedule (Req 6.2, 6.3)", async () => {
    const assetA1 = asset({ id: "a1" });
    const updateAsset = vi.fn().mockResolvedValue(assetA1);
    const getSchedule = vi.fn().mockResolvedValue(scheduleRows);
    const api = makeApi({
      listAssets: vi.fn().mockResolvedValue([assetA1]),
      getSchedule,
      updateAsset,
    });

    const user = await expandSchedule(api);

    // The schedule loaded once when the asset was expanded.
    expect(getSchedule).toHaveBeenCalledTimes(1);

    const input = within(screen.getByRole("table", SCHEDULE_TABLE)).getByLabelText("Depreciation override for 2023");
    await user.type(input, "1952");
    await user.tab(); // blur submits

    // updateAsset carries the override map keyed by year string with the money
    // string value, alongside the asset's other editable fields (Req 6.2, 6.3).
    expect(updateAsset).toHaveBeenCalledWith(
      "prop-1",
      "a1",
      expect.objectContaining({
        description: assetA1.description,
        cost_basis: assetA1.cost_basis,
        placed_in_service_date: assetA1.placed_in_service_date,
        recovery_period_years: assetA1.recovery_period_years,
        depreciation_overrides: { "2023": "1952.00" },
      }),
    );

    // After a successful save the schedule reloads (no full page reload) — the
    // second getSchedule call proves the re-materialized rows are re-fetched.
    await vi.waitFor(() => {
      expect(getSchedule).toHaveBeenCalledTimes(2);
    });
    expect(getSchedule).toHaveBeenLastCalledWith("prop-1", "a1");

    // Success is announced to the user.
    expect(
      await screen.findByText(/depreciation override saved/i),
    ).toBeInTheDocument();
  });

  it("clears an override by sending a map without that year (Req 6.3)", async () => {
    const assetA1 = asset({
      id: "a1",
      depreciation_overrides: { "2023": "1952.00" },
    });
    const updateAsset = vi.fn().mockResolvedValue(assetA1);
    const api = makeApi({
      listAssets: vi.fn().mockResolvedValue([assetA1]),
      getSchedule: vi.fn().mockResolvedValue(scheduleRows),
      updateAsset,
    });

    const user = await expandSchedule(api);

    await user.click(
      within(screen.getByRole("table", SCHEDULE_TABLE)).getByRole("button", {
        name: "Clear depreciation override for 2023",
      }),
    );

    // Clearing removes the year from the override map (reverting to computed).
    expect(updateAsset).toHaveBeenCalledWith(
      "prop-1",
      "a1",
      expect.objectContaining({ depreciation_overrides: {} }),
    );
  });

  it("surfaces a 400 depreciation_overrides.<year> error inline and does not show the override as saved (Req 6.4)", async () => {
    const assetA1 = asset({ id: "a1" });
    const getSchedule = vi.fn().mockResolvedValue(scheduleRows);
    const updateAsset = vi.fn().mockRejectedValue(
      new ApiError(400, "Override exceeds remaining basis.", {
        field: "depreciation_overrides.2023",
        message: "Override exceeds remaining basis.",
      }),
    );
    const api = makeApi({
      listAssets: vi.fn().mockResolvedValue([assetA1]),
      getSchedule,
      updateAsset,
    });

    const user = await expandSchedule(api);
    expect(getSchedule).toHaveBeenCalledTimes(1);

    const input = within(screen.getByRole("table", SCHEDULE_TABLE)).getByLabelText("Depreciation override for 2023");
    await user.type(input, "999999");
    await user.tab(); // blur submits

    expect(updateAsset).toHaveBeenCalledTimes(1);

    // The rejection surfaces inline next to the 2023 control (Req 6.4).
    const alert = await within(screen.getByRole("table", SCHEDULE_TABLE)).findByRole("alert");
    expect(alert).toHaveTextContent("Override exceeds remaining basis.");
    expect(
      within(screen.getByRole("table", SCHEDULE_TABLE)).getByLabelText("Depreciation override for 2023"),
    ).toHaveAttribute("aria-invalid", "true");

    // The schedule is NOT reloaded on failure, so a rejected override is never
    // presented as saved, and no success toast appears (Req 6.4).
    expect(getSchedule).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByText(/depreciation override saved/i),
    ).not.toBeInTheDocument();
  });
});

// Radix registers its outside-interaction listeners on a timer.
const tick = () => new Promise((r) => setTimeout(r, 10));

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const tableEditButton = () =>
  within(screen.getAllByRole("table")[0]).getByRole("button", { name: /edit/i });

describe("AssetsPage — add / edit modal (Req 2, 3, 4, 5, 6)", () => {
  it("creates an asset: closes the modal, reloads, and toasts 'Asset added' (Req 2.2, 2.3)", async () => {
    const user = userEvent.setup();
    const created = asset({ id: "new", description: "New roof" });
    const listAssets = vi
      .fn()
      .mockResolvedValueOnce([])
      .mockResolvedValue([created]);
    const api = makeApi({ listAssets });
    renderPage(api);

    const dialog = await openAddFromEmpty(user);
    await fillAsset(user, dialog, {
      description: "New roof",
      cost: "12000.00",
      date: "2024-03-10",
    });
    await user.click(within(dialog).getByRole("button", { name: /add asset/i }));

    expect(await screen.findByText("Asset added")).toBeInTheDocument();
    await vi.waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(listAssets).toHaveBeenCalledTimes(2);
    expect(
      within(screen.getByRole("table")).getByText("New roof"),
    ).toBeInTheDocument();
  });

  it("opens Edit as a prefilled 'Edit asset' modal and saves with 'Asset updated' (Req 3.1, 3.2)", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      listAssets: vi.fn().mockResolvedValue([asset({ id: "a1" })]),
    });
    renderPage(api);
    await screen.findAllByText("Rental building");

    await user.click(tableEditButton());
    const dialog = await screen.findByRole("dialog", { name: "Edit asset" });
    expect(within(dialog).getByLabelText(/description/i)).toHaveValue(
      "Rental building",
    );
    expect(within(dialog).getByLabelText(/cost basis/i)).toHaveValue(
      "275,000.00",
    );
    expect(within(dialog).getByLabelText(/placed in service/i)).toHaveValue(
      "2023-06-15",
    );
    expect(within(dialog).getByLabelText(/recovery period/i)).toHaveValue(27.5);

    await user.clear(within(dialog).getByLabelText(/description/i));
    await user.type(within(dialog).getByLabelText(/description/i), "Main house");
    await user.click(
      within(dialog).getByRole("button", { name: /save changes/i }),
    );

    expect(api.updateAsset).toHaveBeenCalledWith(
      "prop-1",
      "a1",
      expect.objectContaining({ description: "Main house" }),
    );
    expect(await screen.findByText("Asset updated")).toBeInTheDocument();
    await vi.waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("keeps the modal open, retains values, and shows a form-level alert plus toast for a non-field failure (Req 5.3, 5.4)", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      createAsset: vi
        .fn()
        .mockRejectedValue(
          new ApiError(500, "Database unavailable", {
            message: "Database unavailable",
          }),
        ),
    });
    renderPage(api);

    const dialog = await openAddFromEmpty(user);
    await fillAsset(user, dialog, {
      description: "Garage",
      cost: "9000",
      date: "2024-02-02",
    });
    await user.click(within(dialog).getByRole("button", { name: /add asset/i }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Database unavailable",
    );
    expect(
      await screen.findByText("Could not save the asset"),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Add asset" })).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/description/i)).toHaveValue("Garage");
    expect(within(dialog).getByLabelText(/cost basis/i)).toHaveValue("9,000.00");
    expect(within(dialog).getByLabelText(/placed in service/i)).toHaveValue(
      "2024-02-02",
    );
  });

  it("keeps the modal open with retained values and no toast on a field error (Req 5.1, 5.2)", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      createAsset: vi
        .fn()
        .mockRejectedValue(
          new ApiError(400, "cost_basis must be greater than 0", {
            field: "cost_basis",
            message: "cost_basis must be greater than 0",
          }),
        ),
    });
    renderPage(api);

    const dialog = await openAddFromEmpty(user);
    await fillAsset(user, dialog, {
      description: "Bad asset",
      cost: "0",
      date: "2024-01-01",
    });
    await user.click(within(dialog).getByRole("button", { name: /add asset/i }));

    expect(
      (await within(dialog).findAllByText(/cost_basis must be greater than 0/i))[0],
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Add asset" })).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/description/i)).toHaveValue(
      "Bad asset",
    );
    expect(within(dialog).getByLabelText(/cost basis/i)).toHaveValue("0.00");
    expect(
      screen.queryByText("Could not save the asset"),
    ).not.toBeInTheDocument();

    // Editing the field dismisses its server error.
    await user.type(within(dialog).getByLabelText(/cost basis/i), "1");
    expect(
      within(dialog).queryByText(/cost_basis must be greater than 0/i),
    ).not.toBeInTheDocument();
  });

  it("closes via Cancel, Escape, and backdrop without saving (Req 4.1, 4.2, 4.3)", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);
    await screen.findByText(/no assets yet/i);
    const trigger = () => screen.getByRole("button", { name: /add asset/i });

    // Cancel
    await user.click(trigger());
    let dialog = await screen.findByRole("dialog", { name: "Add asset" });
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));
    await vi.waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );

    // Escape
    await user.click(trigger());
    await screen.findByRole("dialog", { name: "Add asset" });
    await user.keyboard("{Escape}");
    await vi.waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );

    // Backdrop (Radix sets pointer-events: none on body, so dispatch directly)
    await user.click(trigger());
    dialog = await screen.findByRole("dialog", { name: "Add asset" });
    await tick();
    fireEvent.pointerDown(document.body);
    await vi.waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );

    expect(api.createAsset).not.toHaveBeenCalled();
    expect(api.updateAsset).not.toHaveBeenCalled();
  });

  it("clears field and form-level errors when the modal is closed and reopened (Req 5.5/4.4)", async () => {
    const user = userEvent.setup();
    const createAsset = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError(400, "cost_basis must be greater than 0", {
          field: "cost_basis",
          message: "cost_basis must be greater than 0",
        }),
      )
      .mockRejectedValueOnce(
        new ApiError(500, "Database unavailable", {
          message: "Database unavailable",
        }),
      );
    const api = makeApi({ createAsset });
    renderPage(api);

    let dialog = await openAddFromEmpty(user);
    await fillAsset(user, dialog, {
      description: "X",
      cost: "0",
      date: "2024-01-01",
    });
    await user.click(within(dialog).getByRole("button", { name: /add asset/i }));
    expect(
      (await within(dialog).findAllByText(/cost_basis must be greater than 0/i))[0],
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));
    await user.click(await screen.findByRole("button", { name: "Discard" }));
    await vi.waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );

    // Reopen: empty fields, no stale field error.
    await user.click(screen.getByRole("button", { name: /add asset/i }));
    dialog = await screen.findByRole("dialog", { name: "Add asset" });
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText(/cost basis/i)).toHaveValue("");
    expect(within(dialog).getByLabelText(/cost basis/i)).not.toHaveAttribute(
      "aria-invalid",
    );

    // Form-level error is cleared too.
    await fillAsset(user, dialog, {
      description: "Y",
      cost: "5",
      date: "2024-01-01",
    });
    await user.click(within(dialog).getByRole("button", { name: /add asset/i }));
    await within(dialog).findByText("Database unavailable");
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));
    await user.click(await screen.findByRole("button", { name: "Discard" }));
    await vi.waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /add asset/i }));
    dialog = await screen.findByRole("dialog", { name: "Add asset" });
    expect(within(dialog).queryByText("Database unavailable")).toBeNull();
  });

  it("disables inputs and ignores Escape and backdrop while a save is pending (Req 4.6)", async () => {
    const user = userEvent.setup();
    const pending = deferred<DepreciableAsset>();
    const api = makeApi({
      createAsset: vi.fn().mockReturnValue(pending.promise),
      listAssets: vi
        .fn()
        .mockResolvedValueOnce([])
        .mockResolvedValue([asset()]),
    });
    renderPage(api);

    const dialog = await openAddFromEmpty(user);
    await fillAsset(user, dialog, {
      description: "Slow",
      cost: "100",
      date: "2024-01-01",
    });
    await user.click(within(dialog).getByRole("button", { name: /add asset/i }));

    await vi.waitFor(() =>
      expect(within(dialog).getByLabelText(/description/i)).toBeDisabled(),
    );
    expect(within(dialog).getByLabelText(/cost basis/i)).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: /cancel/i })).toBeDisabled();

    await tick();
    await user.keyboard("{Escape}");
    fireEvent.pointerDown(document.body);
    await tick();
    expect(screen.getByRole("dialog", { name: "Add asset" })).toBeInTheDocument();

    pending.resolve(asset());
    await vi.waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("returns focus to the Add trigger after cancel and to the row Edit trigger after save (Req 6.4)", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      listAssets: vi.fn().mockResolvedValue([asset({ id: "a1" })]),
    });
    renderPage(api);
    await screen.findAllByText("Rental building");

    const addButton = screen.getByRole("button", { name: "Add asset" });
    await user.click(addButton);
    let dialog = await screen.findByRole("dialog", { name: "Add asset" });
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));
    await vi.waitFor(() => expect(addButton).toHaveFocus());

    const edit = tableEditButton();
    await user.click(edit);
    dialog = await screen.findByRole("dialog", { name: "Edit asset" });
    await user.click(
      within(dialog).getByRole("button", { name: /save changes/i }),
    );
    await vi.waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    // The refresh updates rows in place, so the same Edit button regains focus.
    await vi.waitFor(() => expect(edit).toHaveFocus());
  });

  it("falls back to the 'Assets' heading when the empty-state trigger is gone (Req 6.5)", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      listAssets: vi
        .fn()
        .mockResolvedValueOnce([])
        .mockResolvedValue([asset({ id: "new" })]),
    });
    renderPage(api);

    const dialog = await openAddFromEmpty(user);
    await fillAsset(user, dialog, {
      description: "Rental building",
      cost: "275000.00",
      date: "2023-06-15",
    });
    await user.click(within(dialog).getByRole("button", { name: /add asset/i }));

    await vi.waitFor(() =>
      expect(screen.getByRole("heading", { name: "Assets" })).toHaveFocus(),
    );
  });

  it("keeps the table mounted while the list refreshes after a save (Req 3.6)", async () => {
    const user = userEvent.setup();
    const refresh = deferred<DepreciableAsset[]>();
    const listAssets = vi
      .fn()
      .mockResolvedValueOnce([asset({ id: "a1" })])
      .mockReturnValueOnce(refresh.promise);
    const api = makeApi({ listAssets });
    renderPage(api);
    await screen.findAllByText("Rental building");

    await user.click(tableEditButton());
    const dialog = await screen.findByRole("dialog", { name: "Edit asset" });
    await user.click(
      within(dialog).getByRole("button", { name: /save changes/i }),
    );

    await vi.waitFor(() => expect(listAssets).toHaveBeenCalledTimes(2));
    // Refresh in flight: no loading state, table still present.
    expect(screen.queryByText(/loading assets/i)).not.toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();

    refresh.resolve([asset({ id: "a1", description: "Renamed" })]);
    expect(
      await within(screen.getByRole("table")).findByText("Renamed"),
    ).toBeInTheDocument();
  });

  it("refreshes an expanded schedule after the asset is updated (Req 3.4)", async () => {
    const user = userEvent.setup();
    const rows: ScheduleRow[] = [
      {
        tax_year: 2023,
        amount: "5833.33",
        remaining_basis: "269166.67",
        method: "straight-line",
        convention: "mid-month",
      },
    ];
    const getSchedule = vi.fn().mockResolvedValue(rows);
    const api = makeApi({
      listAssets: vi.fn().mockResolvedValue([asset({ id: "a1" })]),
      getSchedule,
    });
    renderPage(api);
    await screen.findAllByText("Rental building");

    await user.click(
      within(screen.getByRole("table")).getByRole("button", {
        name: /view schedule/i,
      }),
    );
    await (await scheduleTable()).findByLabelText("Depreciation override for 2023");
    expect(getSchedule).toHaveBeenCalledTimes(1);

    await user.click(tableEditButton());
    const dialog = await screen.findByRole("dialog", { name: "Edit asset" });
    await user.click(
      within(dialog).getByRole("button", { name: /save changes/i }),
    );

    await vi.waitFor(() => expect(getSchedule).toHaveBeenCalledTimes(2));
    expect(getSchedule).toHaveBeenLastCalledWith("prop-1", "a1");
  });
});

describe("AssetsPage — delete failure (Req 13.4)", () => {
  it("shows an error toast with no Undo, leaving the asset listed", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      listAssets: vi
        .fn()
        .mockResolvedValue([asset({ id: "a1", description: "Old roof" })]),
      deleteAsset: vi.fn().mockRejectedValue(new Error("nope")),
    });
    renderPage(api);
    await screen.findAllByText("Old roof");

    await user.click(
      within(screen.getByRole("table")).getByRole("button", {
        name: /delete/i,
      }),
    );
    expect(
      await screen.findByText("Could not delete the asset"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
    expect(api.deleteAsset).toHaveBeenCalledWith("prop-1", "a1");
    expect(screen.queryByText("Asset deleted")).not.toBeInTheDocument();
  });
});

describe("AssetsPage — discard changes (Req 10.2-10.7)", () => {
  type Closer = (user: ReturnType<typeof userEvent.setup>) => Promise<void>;
  const closers: Array<[string, Closer]> = [
    [
      "Escape",
      async (user) => {
        await user.keyboard("{Escape}");
      },
    ],
    [
      "backdrop",
      async () => {
        await tick();
        fireEvent.pointerDown(document.body);
      },
    ],
    [
      "Cancel",
      async (user) => {
        await user.click(
          within(screen.getByRole("dialog")).getByRole("button", {
            name: /cancel/i,
          }),
        );
      },
    ],
  ];

  async function openDirtyAdd(user: ReturnType<typeof userEvent.setup>) {
    const dialog = await openAddFromEmpty(user);
    await user.type(within(dialog).getByLabelText(/description/i), "Garage");
    return dialog;
  }

  it.each(closers)(
    "prompts 'Discard changes?' when closing an edited form via %s",
    async (_name, close) => {
      const user = userEvent.setup();
      const api = makeApi();
      renderPage(api);
      await openDirtyAdd(user);

      await close(user);

      expect(
        await screen.findByRole("dialog", { name: "Discard changes?" }),
      ).toBeInTheDocument();
      expect(api.createAsset).not.toHaveBeenCalled();

      // Keep editing retains the edit; Discard then closes the modal.
      await user.click(screen.getByRole("button", { name: "Keep editing" }));
      expect(
        screen.queryByRole("dialog", { name: "Discard changes?" }),
      ).not.toBeInTheDocument();
      expect(screen.getByLabelText(/description/i)).toHaveValue("Garage");

      await close(user);
      await user.click(await screen.findByRole("button", { name: "Discard" }));
      await vi.waitFor(() =>
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
      );
    },
  );

  it.each(closers)(
    "does not prompt via %s after the edit is restored to the original value",
    async (_name, close) => {
      const user = userEvent.setup();
      const api = makeApi({
        listAssets: vi.fn().mockResolvedValue([asset({ id: "a1" })]),
      });
      renderPage(api);
      await screen.findAllByText("Rental building");

      await user.click(tableEditButton());
      const dialog = await screen.findByRole("dialog", { name: "Edit asset" });
      const description = within(dialog).getByLabelText(/description/i);
      await user.type(description, "X");
      await user.type(description, "{Backspace}");
      expect(description).toHaveValue("Rental building");

      await close(user);

      await vi.waitFor(() =>
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
      );
      expect(screen.queryByText("Discard changes?")).not.toBeInTheDocument();
    },
  );

  it("closes after a successful save without the prompt", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      listAssets: vi
        .fn()
        .mockResolvedValueOnce([])
        .mockResolvedValue([asset({ id: "new" })]),
    });
    renderPage(api);

    const dialog = await openAddFromEmpty(user);
    await fillAsset(user, dialog, {
      description: "New roof",
      cost: "12000.00",
      date: "2024-03-10",
    });
    await user.click(within(dialog).getByRole("button", { name: /add asset/i }));

    await vi.waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(api.createAsset).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Discard changes?")).not.toBeInTheDocument();
  });
});

describe("AssetsPage — load error and retry (Req 14.4-14.6)", () => {
  it("shows a retryable error and recovers on Retry", async () => {
    const user = userEvent.setup();
    const listAssets = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValue([asset()]);
    renderPage(makeApi({ listAssets }));

    const alert = await screen.findByRole("alert");
    await user.click(within(alert).getByRole("button", { name: /retry/i }));

    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(listAssets).toHaveBeenCalledTimes(2);
  });
});

describe("AssetsPage: new=1 parameter", () => {
  it("opens the add dialog once after the load", async () => {
    renderPage(makeApi(), "?new=1");
    expect(
      await screen.findByRole("dialog", { name: "Add asset" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });
  it("does not open the dialog without the parameter", async () => {
    renderPage(makeApi());
    await screen.findAllByRole("button", { name: /add asset/i });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
