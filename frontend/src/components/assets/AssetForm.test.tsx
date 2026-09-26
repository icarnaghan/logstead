import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { AssetForm } from "./AssetForm";
import { DEFAULT_RECOVERY_PERIOD_YEARS, type DepreciableAsset } from "../../api/assets";

/**
 * Component tests for the depreciable-asset form in isolation
 * (task 23.2, Requirements 8.1–8.5).
 *
 * These exercise the form directly with injected handlers (no page, no
 * network): the 27.5-year recovery-period default, explicit recovery periods,
 * edit-mode pre-population, inline field errors, required fields, and the
 * submit / cancel callbacks.
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

describe("AssetForm — recovery-period default (Req 8.4)", () => {
  it("submits the 27.5-year default when the recovery period is left blank", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<AssetForm onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText(/description/i), "New roof");
    await user.type(screen.getByLabelText(/cost basis/i), "12000.00");
    await user.type(screen.getByLabelText(/placed in service/i), "2024-03-10");
    // Deliberately leave "Recovery period" blank.

    await user.click(screen.getByRole("button", { name: /add asset/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({
      description: "New roof",
      cost_basis: "12000.00",
      placed_in_service_date: "2024-03-10",
      recovery_period_years: DEFAULT_RECOVERY_PERIOD_YEARS,
    });
  });

  it("communicates the default via placeholder and helper text", () => {
    render(<AssetForm onSubmit={vi.fn()} />);

    expect(screen.getByLabelText(/recovery period/i)).toHaveAttribute(
      "placeholder",
      "27.5",
    );
    expect(screen.getByText(/default of 27\.5 years/i)).toBeInTheDocument();
  });
});

describe("AssetForm — explicit recovery period (Req 8.1)", () => {
  it("submits an explicit recovery period as-is", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<AssetForm onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText(/description/i), "Appliance");
    await user.type(screen.getByLabelText(/cost basis/i), "5000.00");
    await user.type(screen.getByLabelText(/placed in service/i), "2024-01-01");
    await user.type(screen.getByLabelText(/recovery period/i), "5");

    await user.click(screen.getByRole("button", { name: /add asset/i }));

    expect(onSubmit).toHaveBeenCalledWith({
      description: "Appliance",
      cost_basis: "5000.00",
      placed_in_service_date: "2024-01-01",
      recovery_period_years: 5,
    });
  });
});

describe("AssetForm — edit mode (Req 8.5)", () => {
  it("pre-populates the fields from the supplied asset", () => {
    render(
      <AssetForm
        asset={asset({
          description: "HVAC unit",
          cost_basis: "8000.00",
          placed_in_service_date: "2022-05-01",
          recovery_period_years: 27.5,
        })}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByLabelText(/description/i)).toHaveValue("HVAC unit");
    expect(screen.getByLabelText(/cost basis/i)).toHaveValue("8000.00");
    expect(screen.getByLabelText(/placed in service/i)).toHaveValue(
      "2022-05-01",
    );
    expect(screen.getByLabelText(/recovery period/i)).toHaveValue(27.5);
    // Edit mode uses the "Save changes" submit label.
    expect(
      screen.getByRole("button", { name: /save changes/i }),
    ).toBeInTheDocument();
  });

  it("submits the (unchanged) pre-populated values", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <AssetForm
        asset={asset({
          description: "HVAC unit",
          cost_basis: "8000.00",
          placed_in_service_date: "2022-05-01",
          recovery_period_years: 15,
        })}
        onSubmit={onSubmit}
      />,
    );

    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(onSubmit).toHaveBeenCalledWith({
      description: "HVAC unit",
      cost_basis: "8000.00",
      placed_in_service_date: "2022-05-01",
      recovery_period_years: 15,
    });
  });
});

describe("AssetForm — field errors (Req 8.2, 8.3)", () => {
  it("renders a cost_basis error inline and marks that input invalid", () => {
    render(
      <AssetForm
        onSubmit={vi.fn()}
        fieldErrors={{ cost_basis: "cost_basis must be greater than 0" }}
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/cost_basis must be greater than 0/i);

    const costInput = screen.getByLabelText(/cost basis/i);
    expect(costInput).toHaveAttribute("aria-invalid", "true");
    // The error is associated with the offending control for AT.
    expect(costInput.getAttribute("aria-describedby")).toContain(alert.id);

    // Other inputs are not marked invalid.
    expect(screen.getByLabelText(/description/i)).not.toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });
});

describe("AssetForm — required fields & actions", () => {
  it("marks description, cost basis, and placed-in-service as required", () => {
    render(<AssetForm onSubmit={vi.fn()} />);

    expect(screen.getByLabelText(/description/i)).toBeRequired();
    expect(screen.getByLabelText(/cost basis/i)).toBeRequired();
    expect(screen.getByLabelText(/placed in service/i)).toBeRequired();
  });

  it("calls onCancel when the cancel button is clicked", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<AssetForm onSubmit={vi.fn()} onCancel={onCancel} />);

    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("omits the cancel button when no onCancel handler is provided", () => {
    render(<AssetForm onSubmit={vi.fn()} />);
    expect(
      screen.queryByRole("button", { name: /cancel/i }),
    ).not.toBeInTheDocument();
  });

  it("has no detectable accessibility violations", async () => {
    const { container } = render(
      <AssetForm
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
        fieldErrors={{ cost_basis: "cost_basis must be greater than 0" }}
      />,
    );

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
