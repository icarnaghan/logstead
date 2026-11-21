import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ScheduleEExtractionPage from "./ScheduleEExtractionPage";
import type { ExtractionJobView } from "../api/scheduleEExtraction";

/**
 * Page-level RTL tests for the Schedule E extraction page (tasks 12.2, 12.5).
 *
 * The upload control's api, the poller, and the review form's property loader
 * are all injected seams, so a file selection drives the page through its
 * states without the network. We assert the page mounts the seeded review form
 * on a `draft` job and keeps the manual-form fallback on `failed` /
 * `no_schedule_e_found`.
 */

function view(partial: Partial<ExtractionJobView>): ExtractionJobView {
  return {
    job_id: "job-1",
    status: "complete",
    outcome: "draft",
    message: null,
    review_draft: null,
    ...partial,
  };
}

function uploadApi() {
  const beginExtraction = vi
    .fn()
    .mockResolvedValue({ job_id: "job-1", status: "processing" as const });
  return {
    startExtraction: vi
      .fn()
      .mockResolvedValue({ job_id: "job-1", upload_url: "https://s3/put" }),
    uploadToPresignedUrl: vi.fn().mockResolvedValue(undefined),
    beginExtraction,
  };
}

async function uploadPdf(begin: ReturnType<typeof vi.fn>) {
  const user = userEvent.setup();
  const file = new File(["%PDF-1.4"], "return.pdf", { type: "application/pdf" });
  await user.upload(screen.getByLabelText(/choose your schedule e pages/i), file);
  await waitFor(() => expect(begin).toHaveBeenCalledWith("job-1"));
}

function renderPage(opts: {
  getExtraction: ReturnType<typeof vi.fn>;
  upload: ReturnType<typeof uploadApi>;
}) {
  return render(
    <MemoryRouter>
      <ScheduleEExtractionPage
        pollIntervalMs={10}
        getExtraction={opts.getExtraction}
        upload={opts.upload}
        review={{ loadProperties: vi.fn().mockResolvedValue([]) }}
      />
    </MemoryRouter>,
  );
}

describe("ScheduleEExtractionPage — review mount on a draft job (12.2)", () => {
  it("renders the seeded review form once the job completes with a draft", async () => {
    const upload = uploadApi();
    const getExtraction = vi.fn().mockResolvedValue(
      view({
        status: "complete",
        outcome: "draft",
        review_draft: {
          tax_year: 2023,
          tax_year_needs_verification: false,
          columns: [
            {
              address_text: "12 Maple St",
              address_confidence: 97,
              suggested_property_id: null,
              suggested_property_name: null,
              mapping_confidence: null,
              lines: [
                {
                  schedule_e_line: 3,
                  amount: "24000.00",
                  needs_verification: false,
                  confidence: 98,
                },
              ],
            },
          ],
        },
      }),
    );

    renderPage({ getExtraction, upload });
    await uploadPdf(upload.beginExtraction);

    expect(await screen.findByTestId("extraction-review")).toHaveAttribute(
      "data-column-count",
      "1",
    );
    expect(
      await screen.findByRole("heading", { name: /property column 1/i }),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText(/line 3: rents received/i)).toHaveValue(
      "24000.00",
    );
    // The draft-ready placeholder is replaced by the real form.
    expect(screen.queryByTestId("extraction-ready")).not.toBeInTheDocument();
  });
});

describe("ScheduleEExtractionPage — manual-form fallback (12.5)", () => {
  it("offers the manual Schedule E link when the job failed", async () => {
    const upload = uploadApi();
    const getExtraction = vi.fn().mockResolvedValue(
      view({ status: "failed", outcome: null, message: "a valid PDF is required" }),
    );

    renderPage({ getExtraction, upload });
    await uploadPdf(upload.beginExtraction);

    const link = await screen.findByRole("link", {
      name: /enter your schedule e manually/i,
    });
    expect(link).toHaveAttribute("href", "/imports/schedule-e");
    expect(screen.queryByTestId("extraction-review")).not.toBeInTheDocument();
  });

  it("offers the manual Schedule E link when no Schedule E was found", async () => {
    const upload = uploadApi();
    const getExtraction = vi.fn().mockResolvedValue(
      view({
        status: "complete",
        outcome: "no_schedule_e_found",
        message: "No Schedule E was located in the uploaded document.",
      }),
    );

    renderPage({ getExtraction, upload });
    await uploadPdf(upload.beginExtraction);

    expect(
      await screen.findByText(/no schedule e was located/i),
    ).toBeInTheDocument();
    const link = screen.getByRole("link", {
      name: /enter your schedule e manually/i,
    });
    expect(link).toHaveAttribute("href", "/imports/schedule-e");
    expect(screen.queryByTestId("extraction-review")).not.toBeInTheDocument();
  });
});

describe("ScheduleEExtractionPage — Schedule E-only guidance", () => {
  it("tells the user up front to upload only their Schedule E pages", () => {
    renderPage({ getExtraction: vi.fn(), upload: uploadApi() });

    // The prominent note and the intro both direct the user to Schedule E only.
    expect(
      screen.getByText(/upload only your schedule e pages, not the whole return/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/pdf of just the schedule e pages/i),
    ).toBeInTheDocument();
  });
});
