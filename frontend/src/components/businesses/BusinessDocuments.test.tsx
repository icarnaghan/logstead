import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BusinessDocuments, type BusinessDocumentsApi } from "./BusinessDocuments";
import type { BusinessDocumentWithUrl } from "../../api/businesses";

function doc(
  id: string,
  filename: string,
  contentType = "application/pdf",
): BusinessDocumentWithUrl {
  return {
    document: {
      id,
      business_id: "biz-1",
      s3_key: `business-docs/biz-1/${id}/${filename}`,
      content_type: contentType,
      original_filename: filename,
      uploaded_at: "2024-01-01T00:00:00Z",
    },
    download_url: `https://s3.example/get/${id}`,
  };
}

/** Builds a fake documents API whose list resolves from a mutable store. */
function makeApi(initial: BusinessDocumentWithUrl[] = []): BusinessDocumentsApi & {
  store: BusinessDocumentWithUrl[];
  listDocuments: ReturnType<typeof vi.fn>;
  requestDocumentUpload: ReturnType<typeof vi.fn>;
  uploadToPresignedUrl: ReturnType<typeof vi.fn>;
  deleteDocument: ReturnType<typeof vi.fn>;
} {
  const store = [...initial];
  return {
    store,
    listDocuments: vi.fn(async () => [...store]),
    requestDocumentUpload: vi.fn(
      async (_businessId: string, filename: string, _contentType: string) => ({
        upload_url: `https://s3.example/put/${filename}`,
      }),
    ),
    uploadToPresignedUrl: vi.fn(async () => undefined),
    deleteDocument: vi.fn(async (_businessId: string, documentId: string) => {
      const idx = store.findIndex((d) => d.document.id === documentId);
      if (idx >= 0) store.splice(idx, 1);
    }),
  };
}

function pdfFile(name = "lease.pdf") {
  return new File(["%PDF"], name, { type: "application/pdf" });
}

describe("BusinessDocuments — list (Req 11.4)", () => {
  it("renders documents with a download link using the download_url", async () => {
    const api = makeApi([
      doc("d1", "lease.pdf"),
      doc("d2", "receipt.png", "image/png"),
    ]);
    render(<BusinessDocuments businessId="biz-1" api={api} />);

    const leaseLink = await screen.findByRole("link", { name: "lease.pdf" });
    expect(leaseLink).toHaveAttribute("href", "https://s3.example/get/d1");

    const receiptLink = screen.getByRole("link", { name: "receipt.png" });
    expect(receiptLink).toHaveAttribute("href", "https://s3.example/get/d2");
  });

  it("shows an empty state when there are no documents", async () => {
    const api = makeApi([]);
    render(<BusinessDocuments businessId="biz-1" api={api} />);

    expect(await screen.findByText(/no documents yet/i)).toBeInTheDocument();
  });
});

describe("BusinessDocuments — upload (Req 11.4)", () => {
  it("requests a presigned URL, PUTs the bytes, then shows the new document", async () => {
    const user = userEvent.setup();
    const api = makeApi([]);
    render(<BusinessDocuments businessId="biz-1" api={api} />);

    await screen.findByText(/no documents yet/i);

    const file = pdfFile("lease.pdf");
    // Once the upload succeeds, the refreshed list should include the document.
    api.listDocuments.mockImplementation(async () => [doc("new-lease", "lease.pdf")]);

    const input = screen.getByLabelText(/add a document/i);
    await user.upload(input, file);

    await waitFor(() => {
      expect(api.requestDocumentUpload).toHaveBeenCalledWith(
        "biz-1",
        "lease.pdf",
        "application/pdf",
      );
    });
    expect(api.uploadToPresignedUrl).toHaveBeenCalledWith(
      "https://s3.example/put/lease.pdf",
      file,
    );
    expect(
      await screen.findByRole("link", { name: "lease.pdf" }),
    ).toBeInTheDocument();
  });

  it("accepts an image type (png) by requesting an upload", async () => {
    const api = makeApi([]);
    render(<BusinessDocuments businessId="biz-1" api={api} />);

    await screen.findByText(/no documents yet/i);

    const pngFile = new File(["bytes"], "scan.png", { type: "image/png" });
    const input = screen.getByLabelText(/add a document/i) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [pngFile] } });

    await waitFor(() => {
      expect(api.requestDocumentUpload).toHaveBeenCalledWith(
        "biz-1",
        "scan.png",
        "image/png",
      );
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("BusinessDocuments — type validation (Req 11.4)", () => {
  it("rejects a disallowed type with an accessible error and makes no upload request", async () => {
    const api = makeApi([]);
    render(<BusinessDocuments businessId="biz-1" api={api} />);

    await screen.findByText(/no documents yet/i);

    const badFile = new File(["hello"], "notes.txt", { type: "text/plain" });
    const input = screen.getByLabelText(/add a document/i) as HTMLInputElement;
    // `userEvent.upload` honors the `accept` filter, so a disallowed type never
    // reaches the onChange handler through it. Deliver the file directly via
    // fireEvent to exercise the component's own JS type validation.
    fireEvent.change(input, { target: { files: [badFile] } });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/not an accepted document type/i);
    expect(alert).toHaveTextContent(/PDF, JPEG, PNG, WebP, HEIC, or HEIF/i);
    expect(api.requestDocumentUpload).not.toHaveBeenCalled();
    expect(api.uploadToPresignedUrl).not.toHaveBeenCalled();
  });
});

describe("BusinessDocuments — delete (Req 11.4)", () => {
  it("deletes a document after confirmation and removes it from the list", async () => {
    const user = userEvent.setup();
    const api = makeApi([
      doc("d1", "lease.pdf"),
      doc("d2", "receipt.png", "image/png"),
    ]);
    const confirmDelete = vi.fn(() => true);
    render(
      <BusinessDocuments businessId="biz-1" api={api} confirmDelete={confirmDelete} />,
    );

    await screen.findByRole("link", { name: "lease.pdf" });

    await user.click(screen.getByRole("button", { name: /delete lease\.pdf/i }));

    expect(confirmDelete).toHaveBeenCalled();
    await waitFor(() => {
      expect(api.deleteDocument).toHaveBeenCalledWith("biz-1", "d1");
    });
    await waitFor(() => {
      expect(screen.queryByRole("link", { name: "lease.pdf" })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("link", { name: "receipt.png" })).toBeInTheDocument();
  });

  it("does not delete when confirmation is declined", async () => {
    const user = userEvent.setup();
    const api = makeApi([doc("d1", "lease.pdf")]);
    const confirmDelete = vi.fn(() => false);
    render(
      <BusinessDocuments businessId="biz-1" api={api} confirmDelete={confirmDelete} />,
    );

    await screen.findByRole("link", { name: "lease.pdf" });
    await user.click(screen.getByRole("button", { name: /delete lease\.pdf/i }));

    expect(confirmDelete).toHaveBeenCalled();
    expect(api.deleteDocument).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "lease.pdf" })).toBeInTheDocument();
  });
});

describe("BusinessDocuments — accessibility (Req 12.4)", () => {
  it("has a labelled file input and no detectable axe violations", async () => {
    const api = makeApi([doc("d1", "lease.pdf")]);
    const { container } = render(
      <BusinessDocuments businessId="biz-1" api={api} />,
    );

    await screen.findByRole("link", { name: "lease.pdf" });

    // The file input is reachable by its label.
    expect(screen.getByLabelText(/add a document/i)).toHaveAttribute(
      "type",
      "file",
    );

    // The list is a named list of documents.
    const list = screen.getByRole("list", { name: /business documents/i });
    expect(within(list).getByRole("link", { name: "lease.pdf" })).toBeInTheDocument();

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});

beforeEach(() => {
  vi.restoreAllMocks();
});
