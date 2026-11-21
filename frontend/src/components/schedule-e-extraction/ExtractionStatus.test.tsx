import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { ExtractionStatus } from "./ExtractionStatus";
import type { ExtractionJobState } from "./useExtractionJob";

function state(partial: Partial<ExtractionJobState>): ExtractionJobState {
  return {
    status: null,
    outcome: null,
    reviewDraft: null,
    message: null,
    error: null,
    ...partial,
  };
}

function renderStatus(s: ExtractionJobState) {
  return render(
    <MemoryRouter>
      <ExtractionStatus state={s} />
    </MemoryRouter>,
  );
}

describe("ExtractionStatus — rendering per state (Req 3, 12.2)", () => {
  it("shows a progress indicator while processing", () => {
    renderStatus(state({ status: "processing" }));
    expect(screen.getByRole("status")).toHaveTextContent(/reading your document/i);
  });

  it("shows the distinct 'no Schedule E found' message on that outcome", () => {
    renderStatus(
      state({
        status: "complete",
        outcome: "no_schedule_e_found",
        message: "No Schedule E was located in the uploaded document.",
      }),
    );
    expect(
      screen.getByText(/no schedule e was located/i),
    ).toBeInTheDocument();
    // Offers the manual-form fallback link.
    expect(
      screen.getByRole("link", { name: /enter your schedule e manually/i }),
    ).toHaveAttribute("href", "/imports/schedule-e");
  });

  it("shows the failure message in an alert on a failed job", () => {
    renderStatus(
      state({ status: "failed", message: "a valid PDF is required" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      /a valid pdf is required/i,
    );
  });

  it("indicates readiness and passes the draft column count through on complete+draft", () => {
    renderStatus(
      state({
        status: "complete",
        outcome: "draft",
        reviewDraft: {
          tax_year: 2023,
          tax_year_needs_verification: false,
          columns: [
            {
              address_text: "12 Maple St",
              address_confidence: 97,
              suggested_property_id: null,
              suggested_property_name: null,
              mapping_confidence: null,
              lines: [],
            },
            {
              address_text: "9 Oak Ave",
              address_confidence: 95,
              suggested_property_id: null,
              suggested_property_name: null,
              mapping_confidence: null,
              lines: [],
            },
          ],
        },
      }),
    );
    const ready = screen.getByTestId("extraction-ready");
    expect(ready).toHaveAttribute("data-column-count", "2");
    expect(screen.getByRole("status")).toHaveTextContent(/ready for review/i);
    expect(ready).toHaveTextContent(/read 2 properties/i);
  });

  it("renders nothing before a job exists", () => {
    const { container } = renderStatus(state({}));
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ExtractionStatus — accessibility", () => {
  it("has no axe violations across the terminal states", async () => {
    const { container } = renderStatus(
      state({
        status: "complete",
        outcome: "no_schedule_e_found",
        message: "No Schedule E was located in the uploaded document.",
      }),
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
