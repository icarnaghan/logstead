import { render, screen, within } from "@testing-library/react";
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

function renderPage(api: AssetsApi) {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={["/properties/prop-1/assets"]}>
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

    // ResponsiveTable renders both a <table> and a card fallback, so asset
    // descriptions appear twice; wait for the list to load, then scope to the
    // table representation.
    await screen.findAllByText("Roof replacement");
    const table = screen.getByRole("table");
    expect(within(table).getByText("Roof replacement")).toBeInTheDocument();
    expect(within(table).getByText("HVAC unit")).toBeInTheDocument();
    expect(api.listAssets).toHaveBeenCalledWith("prop-1");
  });

  it("shows an empty state when there are no assets", async () => {
    const api = makeApi();
    renderPage(api);
    expect(
      await screen.findByRole("heading", { name: /no depreciable assets yet/i }),
    ).toBeInTheDocument();
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

    expect(await screen.findByRole("status")).toHaveTextContent(
      /loading assets/i,
    );

    resolve([]);
    await screen.findByRole("heading", { name: /no depreciable assets yet/i });
  });
});

describe("AssetsPage — create with recovery-period default (Req 8.1, 8.4)", () => {
  it("defaults recovery period to 27.5 when the field is left blank", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);

    // Wait for the initial load to settle.
    await screen.findByText(/no depreciable assets yet/i);

    await user.type(screen.getByLabelText(/description/i), "New roof");
    await user.type(screen.getByLabelText(/cost basis/i), "12000.00");
    await user.type(
      screen.getByLabelText(/placed in service/i),
      "2024-03-10",
    );
    // Deliberately leave "Recovery period" blank.

    await user.click(screen.getByRole("button", { name: /add asset/i }));

    expect(api.createAsset).toHaveBeenCalledWith("prop-1", {
      description: "New roof",
      cost_basis: "12000.00",
      placed_in_service_date: "2024-03-10",
      recovery_period_years: 27.5,
    });
  });

  it("communicates the 27.5-year default to the user", async () => {
    const api = makeApi();
    renderPage(api);
    await screen.findByText(/no depreciable assets yet/i);

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
    await screen.findByText(/no depreciable assets yet/i);

    await user.type(screen.getByLabelText(/description/i), "Bad asset");
    await user.type(screen.getByLabelText(/cost basis/i), "0");
    await user.type(
      screen.getByLabelText(/placed in service/i),
      "2024-01-01",
    );
    await user.click(screen.getByRole("button", { name: /add asset/i }));

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

describe("AssetsPage — guarded delete + feedback (Req 4, 5.2)", () => {
  it("confirms before deleting, calls the API, refreshes, and toasts success", async () => {
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

    // The confirm dialog names the asset; the API is not called yet.
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/delete "old roof"/i)).toBeInTheDocument();
    expect(api.deleteAsset).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: /^delete/i }));

    expect(api.deleteAsset).toHaveBeenCalledWith("prop-1", "a1");
    // The list re-fetches after the delete.
    await screen.findByText(/no depreciable assets yet/i);
    // Success toast is announced.
    expect(await screen.findByText("Asset deleted")).toBeInTheDocument();
  });

  it("does not delete when the confirmation is cancelled", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      listAssets: vi
        .fn()
        .mockResolvedValue([asset({ id: "a1", description: "Old roof" })]),
    });

    renderPage(api);
    await screen.findAllByText("Old roof");

    await user.click(
      within(screen.getByRole("table")).getByRole("button", {
        name: /delete/i,
      }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));

    expect(api.deleteAsset).not.toHaveBeenCalled();
    expect(
      within(screen.getByRole("table")).getByText("Old roof"),
    ).toBeInTheDocument();
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
    await screen.findAllByText("Rental building");

    // The view-schedule toggle appears in both the table and card layouts;
    // click the one in the table representation.
    await user.click(
      within(screen.getByRole("table")).getByRole("button", {
        name: /view schedule/i,
      }),
    );

    // The schedule table appears with year / amount / remaining-basis rows.
    const tables = await screen.findAllByRole("table");
    // The last table is the schedule (the first is the asset list).
    const scheduleTable = tables[tables.length - 1];
    expect(within(scheduleTable).getByText("2023")).toBeInTheDocument();
    expect(within(scheduleTable).getByText("$5,833.33")).toBeInTheDocument();
    expect(within(scheduleTable).getByText("$269,166.67")).toBeInTheDocument();
    expect(within(scheduleTable).getByText("2024")).toBeInTheDocument();

    expect(api.getSchedule).toHaveBeenCalledWith("prop-1", "a1");
  });
});
