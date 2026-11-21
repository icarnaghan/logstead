import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { ExtractionReview } from "./ExtractionReview";
import { ApiError } from "../../api/scheduleEImport";
import type { ImportOutcome, ImportSubmission } from "../../api/scheduleEImport";
import type { Property } from "../../api/properties";
import type {
  ExtractedColumn,
  ExtractedLine,
  ReviewDraft,
} from "../../api/scheduleEExtraction";

/**
 * RTL + axe tests for the extraction review screen (task 12.6).
 *
 * The review screen seeds the EXISTING layer-1 `ScheduleEImportForm` from a
 * `ReviewDraft`. Both external calls are injected test seams: `loadProperties`
 * feeds the existing-property select; `submit` stands in for the real
 * `importScheduleE` so the confirm hand-off is observable without the network.
 *
 * Validates: Requirements 7.2, 8.1, 8.2, 8.3, 8.4, 8.5, 9.2, 9.4.
 */

function line(overrides: Partial<ExtractedLine> = {}): ExtractedLine {
  return {
    schedule_e_line: 3,
    amount: "0.00",
    needs_verification: false,
    confidence: 95,
    ...overrides,
  };
}

function column(overrides: Partial<ExtractedColumn> = {}): ExtractedColumn {
  return {
    address_text: "12 Maple St",
    address_confidence: 97,
    suggested_property_id: null,
    suggested_property_name: null,
    mapping_confidence: null,
    lines: [],
    ...overrides,
  };
}

function draft(overrides: Partial<ReviewDraft> = {}): ReviewDraft {
  return {
    tax_year: 2023,
    tax_year_needs_verification: false,
    columns: [column()],
    ...overrides,
  };
}

function property(overrides: Partial<Property> = {}): Property {
  return {
    id: "p1",
    user_id: "u1",
    name: "Maple Duplex",
    address_text: "12 Maple St",
    ...overrides,
  } as Property;
}

function outcome(overrides: Partial<ImportOutcome> = {}): ImportOutcome {
  return {
    tax_year: 2023,
    entries: [
      {
        property_id: "p1",
        created_transaction_ids: ["t1"],
        deleted_prior_count: 0,
        created_inline_property: false,
      },
    ],
    ...overrides,
  };
}

function loader(properties: Property[] = [property()]) {
  return vi.fn().mockResolvedValue(properties);
}

async function waitForLoaded() {
  // One "Select a property" option per column once properties finish loading.
  await screen.findAllByRole("option", { name: /select a property/i });
}

function existingPropertySelect(scope: HTMLElement = document.body) {
  return within(scope).getByRole("combobox", { name: /existing property/i });
}

describe("ExtractionReview — seeds the layer-1 form from the draft", () => {
  it("renders one card per column with pre-filled amounts (8.1, 8.2)", async () => {
    const d = draft({
      columns: [
        column({
          lines: [
            line({ schedule_e_line: 3, amount: "24000.00" }),
            line({ schedule_e_line: 14, amount: "1875.50" }),
          ],
        }),
        column({
          address_text: "9 Oak Ave",
          lines: [line({ schedule_e_line: 3, amount: "12000.00" })],
        }),
      ],
    });
    render(<ExtractionReview reviewDraft={d} submit={vi.fn()} loadProperties={loader()} />);
    await waitForLoaded();

    // One card per extracted column.
    expect(screen.getByRole("heading", { name: /property column 1/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /property column 2/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /property column 3/i }),
    ).not.toBeInTheDocument();

    // Pre-filled amounts land on the right line inputs.
    const col1 = screen
      .getByRole("heading", { name: /property column 1/i })
      .closest("section") as HTMLElement;
    expect(within(col1).getByLabelText(/line 3: rents received/i)).toHaveValue("24000.00");
    expect(within(col1).getByLabelText(/line 14: repairs/i)).toHaveValue("1875.50");
  });

  it("shows the suggested mapping but never auto-applies it (7.2)", async () => {
    const d = draft({
      columns: [
        column({
          suggested_property_id: "p1",
          suggested_property_name: "Maple Duplex",
          mapping_confidence: 0.86,
          lines: [line({ schedule_e_line: 3, amount: "24000.00" })],
        }),
      ],
    });
    const submit = vi.fn().mockResolvedValue(outcome());
    render(
      <ExtractionReview
        reviewDraft={d}
        submit={submit}
        loadProperties={loader([property({ id: "p1", name: "Maple Duplex" })])}
      />,
    );
    await waitForLoaded();

    // The suggestion is surfaced as a (non-error) note naming the property.
    const col1 = screen
      .getByRole("heading", { name: /property column 1/i })
      .closest("section") as HTMLElement;
    expect(within(col1).getByText(/we matched this column to/i)).toHaveTextContent(
      /maple duplex/i,
    );
    expect(within(col1).getByText(/86% confidence/i)).toBeInTheDocument();

    // Pre-selected into the select as a default the user can change — but it is
    // only "confirmed" when the user submits the form (never auto-applied).
    expect(existingPropertySelect(col1)).toHaveValue("p1");
    expect(submit).not.toHaveBeenCalled();
  });

  it("flows an edited amount into the submitted ImportSubmission (8.5)", async () => {
    const user = userEvent.setup();
    const d = draft({
      columns: [
        column({
          suggested_property_id: "p1",
          suggested_property_name: "Maple Duplex",
          mapping_confidence: 0.9,
          lines: [line({ schedule_e_line: 3, amount: "24000.00" })],
        }),
      ],
    });
    const submit = vi.fn().mockResolvedValue(outcome());
    render(
      <ExtractionReview
        reviewDraft={d}
        submit={submit}
        loadProperties={loader([property({ id: "p1" })])}
      />,
    );
    await waitForLoaded();

    const rents = screen.getByLabelText(/line 3: rents received/i);
    await user.clear(rents);
    await user.type(rents, "25000.00");
    await user.click(screen.getByRole("button", { name: /^import schedule e$/i }));

    await waitFor(() => expect(submit).toHaveBeenCalledOnce());
    const body = submit.mock.calls[0][0] as ImportSubmission;
    expect(body.tax_year).toBe(2023);
    expect(body.entries[0].property_id).toBe("p1");
    expect(body.entries[0].lines).toContainEqual({
      schedule_e_line: 3,
      amount: "25000.00",
    });
  });

  it("shows an accessible 'please verify' badge on a flagged line (8.3)", async () => {
    const d = draft({
      columns: [
        column({
          lines: [
            line({ schedule_e_line: 3, amount: "24000.00", needs_verification: false }),
            line({
              schedule_e_line: 14,
              amount: "0.00",
              needs_verification: true,
              confidence: 40,
            }),
          ],
        }),
      ],
    });
    render(<ExtractionReview reviewDraft={d} submit={vi.fn()} loadProperties={loader()} />);
    await waitForLoaded();

    // The flagged line carries an informational "please verify" badge; the
    // non-flagged line does not.
    const verifyBadges = screen.getAllByLabelText(/please verify/i);
    expect(verifyBadges.length).toBeGreaterThanOrEqual(1);

    // The flagged input is NOT marked invalid (verify is informational, not an error).
    const line14 = screen.getByLabelText(/line 14: repairs/i);
    expect(line14).not.toHaveAttribute("aria-invalid", "true");
    // Its describedby points at the verify hint element.
    const describedBy = line14.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy as string)).toHaveTextContent(/verify/i);
  });

  it("never renders a Line 18 field (8.4)", async () => {
    const d = draft({
      columns: [column({ lines: [line({ schedule_e_line: 3, amount: "24000.00" })] })],
    });
    render(<ExtractionReview reviewDraft={d} submit={vi.fn()} loadProperties={loader()} />);
    await waitForLoaded();

    expect(screen.queryByLabelText(/line 18/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: /depreciation/i }),
    ).not.toBeInTheDocument();
  });

  it("flags the tax year for verification when the draft is unsure (6.2)", async () => {
    const d = draft({ tax_year: null, tax_year_needs_verification: true });
    render(<ExtractionReview reviewDraft={d} submit={vi.fn()} loadProperties={loader()} />);
    await waitForLoaded();

    expect(screen.getByTestId("tax-year-verify")).toHaveTextContent(
      /couldn't confidently detect the tax year/i,
    );
  });
});

describe("ExtractionReview — confirm hands off to importScheduleE", () => {
  it("posts to the injected submit and routes a layer-1 validation error to the field (9.2, 9.4)", async () => {
    const user = userEvent.setup();
    const d = draft({
      columns: [
        column({
          suggested_property_id: "p1",
          suggested_property_name: "Maple Duplex",
          mapping_confidence: 0.9,
          lines: [line({ schedule_e_line: 14, amount: "-5.00" })],
        }),
      ],
    });
    const submit = vi.fn().mockRejectedValue(
      new ApiError(400, "bad request", {
        field: "entries[0].lines[14]",
        message: "Property column 1, Line 14 (Repairs): amount must not be negative.",
      }),
    );
    render(
      <ExtractionReview
        reviewDraft={d}
        submit={submit}
        loadProperties={loader([property({ id: "p1" })])}
      />,
    );
    await waitForLoaded();

    await user.click(screen.getByRole("button", { name: /^import schedule e$/i }));

    await waitFor(() => expect(submit).toHaveBeenCalledOnce());
    const alert = await screen.findByText(/line 14 \(repairs\): amount must not be negative/i);
    const line14 = screen.getByLabelText(/line 14: repairs/i);
    expect(line14).toHaveAttribute("aria-invalid", "true");
    expect(line14).toHaveAttribute("aria-describedby", alert.id);
  });
});

describe("ExtractionReview — accessibility", () => {
  it("has no axe violations with pre-filled amounts, a suggestion, and a verify badge", async () => {
    const d = draft({
      columns: [
        column({
          suggested_property_id: "p1",
          suggested_property_name: "Maple Duplex",
          mapping_confidence: 0.86,
          lines: [
            line({ schedule_e_line: 3, amount: "24000.00" }),
            line({
              schedule_e_line: 14,
              amount: "0.00",
              needs_verification: true,
              confidence: 40,
            }),
          ],
        }),
      ],
    });
    const { container } = render(
      <ExtractionReview
        reviewDraft={d}
        submit={vi.fn()}
        loadProperties={loader([property({ id: "p1" })])}
      />,
    );
    await waitForLoaded();

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
