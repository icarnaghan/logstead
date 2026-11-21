import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { ScheduleEImportForm } from "./ScheduleEImportForm";
import { ApiError } from "../../api/scheduleEImport";
import type { ImportOutcome, ImportSubmission } from "../../api/scheduleEImport";
import type { Property } from "../../api/properties";

/**
 * Component tests for the guided multi-property Schedule E import form
 * (Requirements 1.2, 1.3, 1.4, 1.6, 1.7, 2.1, 2.2, 2.5, 5.2, 9.6).
 *
 * Both external calls are injected as test seams: `loadProperties` feeds the
 * existing-property select; `submit` stands in for the real `importScheduleE`.
 */

function property(overrides: Partial<Property> = {}): Property {
  return {
    id: "p1",
    user_id: "u1",
    name: "Maple Duplex",
    address_text: "1 Maple St",
    ...overrides,
  };
}

function outcome(overrides: Partial<ImportOutcome> = {}): ImportOutcome {
  return {
    tax_year: 2023,
    entries: [
      {
        property_id: "p1",
        created_transaction_ids: ["t1", "t2"],
        deleted_prior_count: 0,
        created_inline_property: false,
      },
    ],
    ...overrides,
  };
}

/** Resolve the properties loader and let the select settle to "ready". */
function loader(properties: Property[] = [property()]) {
  return vi.fn().mockResolvedValue(properties);
}

async function waitForLoaded() {
  // The select shows "Select a property" (not "Loading…") once loaded.
  await screen.findByRole("option", { name: /select a property/i });
}

/**
 * The existing-property `<select>`. The literal "Existing property" label also
 * appears in the radio choice "Use an existing property", so target the
 * combobox role specifically.
 */
function existingPropertySelect(scope: HTMLElement = document.body) {
  return within(scope).getByRole("combobox", { name: /existing property/i });
}

describe("ScheduleEImportForm — tax year selected once", () => {
  it("renders a single tax-year input shared by all columns", async () => {
    render(<ScheduleEImportForm submit={vi.fn()} loadProperties={loader()} />);
    await waitForLoaded();

    const yearInputs = screen.getAllByLabelText(/tax year/i);
    expect(yearInputs).toHaveLength(1);
    expect(yearInputs[0]).toHaveAttribute("type", "number");
  });

  it("starts with exactly one property column", async () => {
    render(<ScheduleEImportForm submit={vi.fn()} loadProperties={loader()} />);
    await waitForLoaded();

    expect(screen.getByRole("heading", { name: /property column 1/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /property column 2/i }),
    ).not.toBeInTheDocument();
  });
});

describe("ScheduleEImportForm — add / remove entry columns", () => {
  it("adds and removes property columns", async () => {
    const user = userEvent.setup();
    render(<ScheduleEImportForm submit={vi.fn()} loadProperties={loader()} />);
    await waitForLoaded();

    // Only one column → no remove control yet.
    expect(screen.queryByRole("button", { name: /remove column/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /add property column/i }));
    expect(screen.getByRole("heading", { name: /property column 2/i })).toBeInTheDocument();

    // Now removal is available; remove the second column.
    await user.click(screen.getByRole("button", { name: /remove column 2/i }));
    expect(
      screen.queryByRole("heading", { name: /property column 2/i }),
    ).not.toBeInTheDocument();
  });
});

describe("ScheduleEImportForm — existing select vs inline create", () => {
  it("defaults to the existing-property select listing loaded properties", async () => {
    render(
      <ScheduleEImportForm
        submit={vi.fn()}
        loadProperties={loader([property({ id: "p1", name: "Maple Duplex" })])}
      />,
    );
    await waitForLoaded();

    const select = existingPropertySelect();
    expect(within(select).getByRole("option", { name: /maple duplex/i })).toBeInTheDocument();
    // No inline-create fields until the user toggles.
    expect(screen.queryByLabelText(/new property name/i)).not.toBeInTheDocument();
  });

  it("switches a column to inline create and submits new_property", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue(outcome());
    render(<ScheduleEImportForm submit={submit} loadProperties={loader()} />);
    await waitForLoaded();

    await user.click(screen.getByLabelText(/create a new property/i));
    await user.type(screen.getByLabelText(/new property name/i), "Oak Cottage");
    await user.type(screen.getByLabelText(/new property address/i), "9 Oak Rd");
    await user.type(screen.getByLabelText(/line 3: rents received/i), "12000.00");

    await user.click(screen.getByRole("button", { name: /^import schedule e$/i }));

    await waitFor(() => expect(submit).toHaveBeenCalledOnce());
    const body = submit.mock.calls[0][0] as ImportSubmission;
    expect(body.entries[0].new_property).toEqual({
      name: "Oak Cottage",
      address_text: "9 Oak Rd",
    });
    expect(body.entries[0].property_id).toBeUndefined();
    expect(body.entries[0].lines).toContainEqual({
      schedule_e_line: 3,
      amount: "12000.00",
    });
  });

  it("submits an existing property_id with the selected tax year", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue(outcome());
    render(
      <ScheduleEImportForm
        submit={submit}
        loadProperties={loader([property({ id: "p1" })])}
      />,
    );
    await waitForLoaded();

    await user.clear(screen.getByLabelText(/tax year/i));
    await user.type(screen.getByLabelText(/tax year/i), "2022");
    await user.selectOptions(existingPropertySelect(), "p1");
    await user.type(screen.getByLabelText(/line 14: repairs/i), "1875.50");
    await user.click(screen.getByRole("button", { name: /^import schedule e$/i }));

    await waitFor(() => expect(submit).toHaveBeenCalledOnce());
    const body = submit.mock.calls[0][0] as ImportSubmission;
    expect(body.tax_year).toBe(2022);
    expect(body.entries[0].property_id).toBe("p1");
    expect(body.entries[0].lines).toEqual([
      { schedule_e_line: 14, amount: "1875.50" },
    ]);
  });

  it("attaches the Line 19 description to the Other line only", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue(outcome());
    render(
      <ScheduleEImportForm
        submit={submit}
        loadProperties={loader([property({ id: "p1" })])}
      />,
    );
    await waitForLoaded();

    await user.selectOptions(existingPropertySelect(), "p1");
    await user.type(screen.getByLabelText(/line 19: other/i), "320.00");
    await user.type(screen.getByLabelText(/line 19 description/i), "HOA dues");
    await user.click(screen.getByRole("button", { name: /^import schedule e$/i }));

    await waitFor(() => expect(submit).toHaveBeenCalledOnce());
    const body = submit.mock.calls[0][0] as ImportSubmission;
    expect(body.entries[0].lines).toContainEqual({
      schedule_e_line: 19,
      amount: "320.00",
      description: "HOA dues",
    });
  });
});

describe("ScheduleEImportForm — line fields present, no Line 18", () => {
  it("renders income 3-4, expenses 5-17, and Line 19 but never Line 18", async () => {
    render(<ScheduleEImportForm submit={vi.fn()} loadProperties={loader()} />);
    await waitForLoaded();

    // Income + expense lines present.
    expect(screen.getByLabelText(/line 3: rents received/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/line 4: royalties/i)).toBeInTheDocument();
    for (let line = 5; line <= 17; line += 1) {
      expect(screen.getByLabelText(new RegExp(`line ${line}:`, "i"))).toBeInTheDocument();
    }
    expect(screen.getByLabelText(/line 19: other/i)).toBeInTheDocument();

    // Line 18 (Depreciation) must never be offered as an input. (The
    // depreciation-not-imported notice legitimately mentions the word.)
    expect(screen.queryByLabelText(/line 18/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: /depreciation/i }),
    ).not.toBeInTheDocument();
  });
});

describe("ScheduleEImportForm — depreciation notice", () => {
  it("shows the depreciation-not-imported reminder", async () => {
    render(<ScheduleEImportForm submit={vi.fn()} loadProperties={loader()} />);
    await waitForLoaded();

    const note = screen.getByRole("note");
    expect(note).toHaveTextContent(/depreciation \(line 18\) is not imported/i);
  });
});

describe("ScheduleEImportForm — structured server errors route to the right place", () => {
  it("routes a tax_year error to the top-level tax-year input", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockRejectedValue(
      new ApiError(400, "bad request", {
        field: "tax_year",
        message: "Enter a valid four-digit tax year.",
      }),
    );
    render(<ScheduleEImportForm submit={submit} loadProperties={loader()} />);
    await waitForLoaded();

    await user.selectOptions(existingPropertySelect(), "p1");
    await user.type(screen.getByLabelText(/line 3: rents received/i), "100.00");
    await user.click(screen.getByRole("button", { name: /^import schedule e$/i }));

    const alert = await screen.findByText(/valid four-digit tax year/i);
    const yearInput = screen.getByLabelText(/tax year/i);
    expect(yearInput).toHaveAttribute("aria-invalid", "true");
    expect(yearInput).toHaveAttribute("aria-describedby", alert.id);
  });

  it("routes an entries[i].lines[n] error beside the right column's line input", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockRejectedValue(
      new ApiError(400, "bad request", {
        field: "entries[1].lines[14]",
        message: "Property column 2, Line 14 (Repairs): amount must not be negative.",
      }),
    );
    render(<ScheduleEImportForm submit={submit} loadProperties={loader()} />);
    await waitForLoaded();

    // Add a second column so entries[1] exists.
    await user.click(screen.getByRole("button", { name: /add property column/i }));
    await user.click(screen.getByRole("button", { name: /^import schedule e$/i }));

    const alert = await screen.findByText(/line 14 \(repairs\): amount must not be negative/i);
    // The error attaches to the second column's Line 14 input.
    const column2 = screen
      .getByRole("heading", { name: /property column 2/i })
      .closest("section") as HTMLElement;
    const line14 = within(column2).getByLabelText(/line 14: repairs/i);
    expect(line14).toHaveAttribute("aria-invalid", "true");
    expect(line14).toHaveAttribute("aria-describedby", alert.id);
  });

  it("routes an entry-level duplicate-mapping error to the right card", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockRejectedValue(
      new ApiError(400, "bad request", {
        field: "entries[0]",
        message: "Each property column must map to a distinct property.",
      }),
    );
    render(<ScheduleEImportForm submit={submit} loadProperties={loader()} />);
    await waitForLoaded();

    await user.click(screen.getByRole("button", { name: /^import schedule e$/i }));

    const column1 = screen
      .getByRole("heading", { name: /property column 1/i })
      .closest("section") as HTMLElement;
    expect(
      within(column1).getByText(/map to a distinct property/i),
    ).toBeInTheDocument();
  });

  it("routes a new_property field error beside the inline-create input", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockRejectedValue(
      new ApiError(400, "bad request", {
        field: "entries[0].new_property.name",
        message: "Name is required.",
      }),
    );
    render(<ScheduleEImportForm submit={submit} loadProperties={loader()} />);
    await waitForLoaded();

    await user.click(screen.getByLabelText(/create a new property/i));
    await user.click(screen.getByRole("button", { name: /^import schedule e$/i }));

    const alert = await screen.findByText(/^name is required\.$/i);
    const nameInput = screen.getByLabelText(/new property name/i);
    expect(nameInput).toHaveAttribute("aria-invalid", "true");
    expect(nameInput).toHaveAttribute("aria-describedby", alert.id);
  });

  it("routes a submission-level entries error to the top", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockRejectedValue(
      new ApiError(400, "bad request", {
        field: "entries",
        message: "At least one property column is required.",
      }),
    );
    render(<ScheduleEImportForm submit={submit} loadProperties={loader()} />);
    await waitForLoaded();

    await user.click(screen.getByRole("button", { name: /^import schedule e$/i }));

    expect(
      await screen.findByText(/at least one property column is required/i),
    ).toBeInTheDocument();
  });
});

describe("ScheduleEImportForm — success summary", () => {
  it("reports the per-entry outcome on success", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue(
      outcome({
        tax_year: 2023,
        entries: [
          {
            property_id: "p1",
            created_transaction_ids: ["t1", "t2"],
            deleted_prior_count: 1,
            created_inline_property: false,
          },
        ],
      }),
    );
    render(<ScheduleEImportForm submit={submit} loadProperties={loader()} />);
    await waitForLoaded();

    await user.selectOptions(existingPropertySelect(), "p1");
    await user.type(screen.getByLabelText(/line 3: rents received/i), "24000.00");
    await user.click(screen.getByRole("button", { name: /^import schedule e$/i }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/imported schedule e for tax year 2023/i);
    expect(status).toHaveTextContent(/2 transactions created/i);
    expect(status).toHaveTextContent(/1 prior imported replaced/i);
  });
});

describe("ScheduleEImportForm — accessibility", () => {
  it("has no axe violations", async () => {
    const { container } = render(
      <ScheduleEImportForm submit={vi.fn()} loadProperties={loader()} />,
    );
    await waitForLoaded();

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });

  it("has no axe violations with two columns and inline create active", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <ScheduleEImportForm submit={vi.fn()} loadProperties={loader()} />,
    );
    await waitForLoaded();

    await user.click(screen.getByRole("button", { name: /add property column/i }));
    await user.click(screen.getAllByLabelText(/create a new property/i)[0]);

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
