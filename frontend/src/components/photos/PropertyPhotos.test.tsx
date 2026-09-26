import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PropertyPhotos } from "./PropertyPhotos";
import type { PhotoWithUrl, PresignedUpload } from "../../api/photos";

function photo(
  id: string,
  filename: string,
  contentType = "image/jpeg",
): PhotoWithUrl {
  return {
    photo: {
      id,
      property_id: "prop-1",
      s3_key: `photos/prop-1/${id}/${filename}`,
      content_type: contentType,
      original_filename: filename,
      uploaded_at: "2024-01-01T00:00:00Z",
    },
    display_url: `https://s3.example/${id}`,
  };
}

function presign(id: string, filename: string, contentType: string): PresignedUpload {
  return {
    upload_url: `https://s3.example/put/${id}`,
    photo: {
      id,
      property_id: "prop-1",
      s3_key: `photos/prop-1/${id}/${filename}`,
      content_type: contentType,
      original_filename: filename,
      uploaded_at: null,
    },
  };
}

/** Builds a fake photos API whose list resolves from a mutable store. */
function makeApi(initial: PhotoWithUrl[] = []) {
  const store = [...initial];
  return {
    store,
    listPhotos: vi.fn(async () => [...store]),
    requestUpload: vi.fn(async (_propertyId: string, filename: string, contentType: string) =>
      presign(`new-${filename}`, filename, contentType),
    ),
    uploadToPresignedUrl: vi.fn(async () => undefined),
    deletePhoto: vi.fn(async (_propertyId: string, photoId: string) => {
      const idx = store.findIndex((p) => p.photo.id === photoId);
      if (idx >= 0) store.splice(idx, 1);
    }),
  };
}

function jpegFile(name = "kitchen.jpg") {
  return new File(["bytes"], name, { type: "image/jpeg" });
}

describe("PropertyPhotos — gallery (Req 4.3)", () => {
  it("renders photos with alt text from the original filename", async () => {
    const api = makeApi([photo("p1", "front.jpg"), photo("p2", "back.png", "image/png")]);
    render(<PropertyPhotos propertyId="prop-1" api={api} />);

    expect(await screen.findByAltText("front.jpg")).toBeInTheDocument();
    expect(screen.getByAltText("back.png")).toBeInTheDocument();
  });

  it("shows an empty state when there are no photos", async () => {
    const api = makeApi([]);
    render(<PropertyPhotos propertyId="prop-1" api={api} />);

    expect(await screen.findByText(/no photos yet/i)).toBeInTheDocument();
  });
});

describe("PropertyPhotos — upload (Req 4.1)", () => {
  it("requests a presigned URL, PUTs the bytes, then shows the new photo", async () => {
    const user = userEvent.setup();
    const api = makeApi([]);
    render(<PropertyPhotos propertyId="prop-1" api={api} />);

    await screen.findByText(/no photos yet/i);

    const file = jpegFile("kitchen.jpg");
    // Once the upload succeeds, the refreshed list should include the photo.
    api.listPhotos.mockImplementation(async () => [photo("new-kitchen.jpg", "kitchen.jpg")]);

    const input = screen.getByLabelText(/add a photo/i);
    await user.upload(input, file);

    await waitFor(() => {
      expect(api.requestUpload).toHaveBeenCalledWith(
        "prop-1",
        "kitchen.jpg",
        "image/jpeg",
      );
    });
    expect(api.uploadToPresignedUrl).toHaveBeenCalledWith(
      "https://s3.example/put/new-kitchen.jpg",
      file,
    );
    expect(await screen.findByAltText("kitchen.jpg")).toBeInTheDocument();
  });
});

describe("PropertyPhotos — type validation (Req 4.2)", () => {
  it("rejects a disallowed type with an accessible error and makes no upload request", async () => {
    const api = makeApi([]);
    render(<PropertyPhotos propertyId="prop-1" api={api} />);

    await screen.findByText(/no photos yet/i);

    const badFile = new File(["%PDF"], "summary.pdf", {
      type: "application/pdf",
    });
    const input = screen.getByLabelText(/add a photo/i) as HTMLInputElement;
    // `userEvent.upload` honors the `accept` filter, so a disallowed type never
    // reaches the onChange handler through it. Deliver the file directly via
    // fireEvent to exercise the component's own JS type validation.
    fireEvent.change(input, { target: { files: [badFile] } });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/not an accepted image type/i);
    expect(alert).toHaveTextContent(/JPEG, PNG, WebP, HEIC, or HEIF/i);
    expect(api.requestUpload).not.toHaveBeenCalled();
    expect(api.uploadToPresignedUrl).not.toHaveBeenCalled();
  });
});

describe("PropertyPhotos — delete (Req 4.4)", () => {
  it("deletes a photo after confirmation and removes it from the gallery", async () => {
    const user = userEvent.setup();
    const api = makeApi([photo("p1", "front.jpg"), photo("p2", "back.png", "image/png")]);
    const confirmDelete = vi.fn(() => true);
    render(
      <PropertyPhotos propertyId="prop-1" api={api} confirmDelete={confirmDelete} />,
    );

    await screen.findByAltText("front.jpg");

    await user.click(screen.getByRole("button", { name: /delete front\.jpg/i }));

    expect(confirmDelete).toHaveBeenCalled();
    await waitFor(() => {
      expect(api.deletePhoto).toHaveBeenCalledWith("prop-1", "p1");
    });
    await waitFor(() => {
      expect(screen.queryByAltText("front.jpg")).not.toBeInTheDocument();
    });
    expect(screen.getByAltText("back.png")).toBeInTheDocument();
  });

  it("does not delete when confirmation is declined", async () => {
    const user = userEvent.setup();
    const api = makeApi([photo("p1", "front.jpg")]);
    const confirmDelete = vi.fn(() => false);
    render(
      <PropertyPhotos propertyId="prop-1" api={api} confirmDelete={confirmDelete} />,
    );

    await screen.findByAltText("front.jpg");
    await user.click(screen.getByRole("button", { name: /delete front\.jpg/i }));

    expect(confirmDelete).toHaveBeenCalled();
    expect(api.deletePhoto).not.toHaveBeenCalled();
    expect(screen.getByAltText("front.jpg")).toBeInTheDocument();
  });
});

describe("PropertyPhotos — accessibility (Req 14.4)", () => {
  it("has a labelled file input and no detectable axe violations", async () => {
    const api = makeApi([photo("p1", "front.jpg")]);
    const { container } = render(<PropertyPhotos propertyId="prop-1" api={api} />);

    await screen.findByAltText("front.jpg");

    // The file input is reachable by its label.
    expect(screen.getByLabelText(/add a photo/i)).toHaveAttribute("type", "file");

    // The gallery is a named list of images.
    const list = screen.getByRole("list", { name: /property photos/i });
    expect(within(list).getByAltText("front.jpg")).toBeInTheDocument();

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});

beforeEach(() => {
  vi.restoreAllMocks();
});
