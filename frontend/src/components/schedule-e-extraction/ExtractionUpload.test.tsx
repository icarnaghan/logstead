import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { axe } from "vitest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ExtractionUpload,
  MAX_UPLOAD_PAGES,
  type ExtractionUploadApi,
} from "./ExtractionUpload";

/**
 * Builds a fake extraction api whose three functions resolve in order and
 * record their calls, so tests can assert the presign → PUT → begin sequence
 * without any network.
 */
function makeApi(overrides: Partial<ExtractionUploadApi> = {}) {
  const calls: string[] = [];
  const api: ExtractionUploadApi = {
    startExtraction: vi.fn(async () => {
      calls.push("start");
      return { job_id: "job-1", upload_url: "https://s3.example/put/job-1" };
    }),
    uploadToPresignedUrl: vi.fn(async () => {
      calls.push("upload");
    }),
    beginExtraction: vi.fn(async () => {
      calls.push("begin");
      return { job_id: "job-1", status: "processing" as const };
    }),
    ...overrides,
  };
  return { api, calls };
}

function pdfFile(name = "2023-return.pdf") {
  return new File(["%PDF-1.7"], name, { type: "application/pdf" });
}

describe("ExtractionUpload — client-side PDF guard (Req 1.3, 1.4)", () => {
  it("rejects a non-PDF file before any URL is requested, with an accessible error", async () => {
    const { api } = makeApi();
    const onJobStarted = vi.fn();
    render(<ExtractionUpload onJobStarted={onJobStarted} api={api} />);

    const bad = new File(["img"], "receipt.png", { type: "image/png" });
    const input = screen.getByLabelText(/choose your schedule e pages/i);
    fireEvent.change(input, { target: { files: [bad] } });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/not a pdf/i);
    expect(api.startExtraction).not.toHaveBeenCalled();
    expect(api.uploadToPresignedUrl).not.toHaveBeenCalled();
    expect(api.beginExtraction).not.toHaveBeenCalled();
    expect(onJobStarted).not.toHaveBeenCalled();
  });
});

describe("ExtractionUpload — happy path (Req 2.1)", () => {
  it("drives startExtraction → uploadToPresignedUrl → beginExtraction in order and lifts the job id", async () => {
    const { api, calls } = makeApi();
    const onJobStarted = vi.fn();
    render(<ExtractionUpload onJobStarted={onJobStarted} api={api} />);

    const file = pdfFile("2023-return.pdf");
    const input = screen.getByLabelText(/choose your schedule e pages/i);
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(onJobStarted).toHaveBeenCalledWith("job-1"));

    expect(api.startExtraction).toHaveBeenCalledWith(
      "2023-return.pdf",
      "application/pdf",
    );
    expect(api.uploadToPresignedUrl).toHaveBeenCalledWith(
      "https://s3.example/put/job-1",
      file,
    );
    expect(api.beginExtraction).toHaveBeenCalledWith("job-1");
    // Strict ordering of the three steps.
    expect(calls).toEqual(["start", "upload", "begin"]);
  });

  it("surfaces an accessible error when a step fails and does not lift a job id", async () => {
    const { api } = makeApi({
      uploadToPresignedUrl: vi.fn(async () => {
        throw new Error("S3 said no");
      }),
    });
    const onJobStarted = vi.fn();
    render(<ExtractionUpload onJobStarted={onJobStarted} api={api} />);

    const input = screen.getByLabelText(/choose your schedule e pages/i);
    fireEvent.change(input, { target: { files: [pdfFile()] } });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/couldn't start extraction/i);
    expect(api.beginExtraction).not.toHaveBeenCalled();
    expect(onJobStarted).not.toHaveBeenCalled();
  });
});

describe("ExtractionUpload — Schedule E-only guidance", () => {
  it("tells the user to upload only their Schedule E pages, with the page limit", () => {
    const { api } = makeApi();
    render(<ExtractionUpload onJobStarted={vi.fn()} api={api} />);

    const hint = screen.getByText(/only your schedule e pages/i).closest("p");
    expect(hint).not.toBeNull();
    expect(hint).toHaveTextContent(/not your whole tax return/i);
    expect(hint).toHaveTextContent(new RegExp(`${MAX_UPLOAD_PAGES} pages`));
  });

  it("associates the guidance with the file input for assistive tech", () => {
    const { api } = makeApi();
    render(<ExtractionUpload onJobStarted={vi.fn()} api={api} />);

    const input = screen.getByLabelText(/choose your schedule e pages/i);
    const describedBy = (input.getAttribute("aria-describedby") ?? "").split(" ");
    const hint = screen.getByText(/only your schedule e pages/i).closest("p");
    expect(hint?.id).toBeTruthy();
    expect(describedBy).toContain(hint?.id);
  });

  it("points a non-PDF rejection back at Schedule E pages", async () => {
    const { api } = makeApi();
    render(<ExtractionUpload onJobStarted={vi.fn()} api={api} />);

    const bad = new File(["img"], "receipt.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText(/choose your schedule e pages/i), {
      target: { files: [bad] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /just your schedule e pages/i,
    );
  });
});

describe("ExtractionUpload — accessibility", () => {
  it("has a labelled file input and no axe violations", async () => {
    const { api } = makeApi();
    const { container } = render(
      <ExtractionUpload onJobStarted={vi.fn()} api={api} />,
    );

    expect(screen.getByLabelText(/choose your schedule e pages/i)).toHaveAttribute(
      "type",
      "file",
    );

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});

beforeEach(() => {
  vi.restoreAllMocks();
});
