import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { AssetList } from "./AssetList";
import type { DepreciableAsset } from "../../api/assets";

/**
 * Component tests for the depreciable-asset list (task 23.2,
 * Requirements 8.5, 8.6, 8.7, 9.4).
 *
 * Handlers are injected as spies (no page, no network). These tests assert the
 * rendered columns, that the edit / delete / view-schedule actions call their
 * handlers, that the view-schedule toggle exposes aria-expanded, and the empty
 * state.
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

function handlers() {
  return {
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    onToggleSchedule: vi.fn(),
  };
}

describe("AssetList — rendering (Req 8.7)", () => {
  it("renders description, cost basis, placed-in-service, and recovery period", () => {
    const h = handlers();
    render(
      <AssetList
        assets={[
          asset({
            id: "a1",
            description: "HVAC unit",
            cost_basis: "8000.00",
            placed_in_service_date: "2022-05-01",
            recovery_period_years: 15,
          }),
        ]}
        {...h}
      />,
    );

    const table = screen.getByRole("table");
    expect(within(table).getByText("HVAC unit")).toBeInTheDocument();
    expect(within(table).getByText("8000.00")).toBeInTheDocument();
    expect(within(table).getByText("2022-05-01")).toBeInTheDocument();
    expect(within(table).getByText("15")).toBeInTheDocument();
  });

  it("shows an empty state when there are no assets", () => {
    const h = handlers();
    render(<AssetList assets={[]} {...h} />);

    expect(
      screen.getByText(/no depreciable assets yet/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("AssetList — actions (Req 8.5, 8.6, 9.4)", () => {
  it("calls onEdit / onDelete / onToggleSchedule with the row's asset", async () => {
    const user = userEvent.setup();
    const h = handlers();
    const a = asset({ id: "a1" });
    render(<AssetList assets={[a]} {...h} />);

    await user.click(screen.getByRole("button", { name: /view schedule/i }));
    expect(h.onToggleSchedule).toHaveBeenCalledWith(a);

    await user.click(screen.getByRole("button", { name: /edit/i }));
    expect(h.onEdit).toHaveBeenCalledWith(a);

    await user.click(screen.getByRole("button", { name: /delete/i }));
    expect(h.onDelete).toHaveBeenCalledWith(a);
  });

  it("exposes aria-expanded on the view-schedule toggle", () => {
    const h = handlers();
    const a = asset({ id: "a1" });

    const { rerender } = render(
      <AssetList assets={[a]} expandedAssetId={null} {...h} />,
    );

    expect(
      screen.getByRole("button", { name: /view schedule/i }),
    ).toHaveAttribute("aria-expanded", "false");

    // When this asset is the expanded one, the toggle flips to collapse/expanded.
    rerender(<AssetList assets={[a]} expandedAssetId="a1" {...h} />);

    expect(
      screen.getByRole("button", { name: /hide schedule/i }),
    ).toHaveAttribute("aria-expanded", "true");
  });
});

describe("AssetList — accessibility", () => {
  it("has no detectable accessibility violations", async () => {
    const h = handlers();
    const { container } = render(
      <AssetList
        assets={[
          asset({ id: "a1", description: "Rental building" }),
          asset({ id: "a2", description: "HVAC unit" }),
        ]}
        {...h}
      />,
    );

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
