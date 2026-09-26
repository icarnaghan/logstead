import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PropertyPhotos } from "./PropertyPhotos";
import type { PhotoWithUrl, PresignedUpload } from "../../api/photos";

/**
 * Deeper property-photos flow coverage (Requirement 4). Complements
 * PropertyPhotos.test.tsx without duplicating it: the full request-URL → PUT →
 * refresh happy path, an upload failure that leaves the gallery unchanged, a
 * list-load error with a working retry affordance, and keyboard operability of
 * the delete control. The photos API is fully injected — no network.
 */

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

/** A fake photos API whose list resolves from a mutable store. */
function makeApi(initial: PhotoWithUrl[] = []) {
  const store = [...initial];
  return {
    store,
    listPhotos: vi.fn(async () => [...store]),
    requestUpload: vi.fn(
      async (_propertyId: string, filename: string, contentType: string) =>
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

describe("PropertyPhotos — full upload happy path (Req 4.1)", () => {
  it("requests a URL, PUTs the bytes with the file, refreshes, and shows the photo", async () => {
    const user = userEvent.setup();
    const api = makeApi([]);
    render(<PropertyPhotos propertyId="prop-1" api={api} />);

    await screen.findByText(/no photos yet/i);

    const file = jpegFile("kitchen.jpg");
    // After the upload the refreshed list contains the new photo.
    api.listPhotos.mockImplementation(async () => [
      photo("new-kitchen.jpg", "kitchen.jpg"),
    ]);

    await user.upload(screen.getByLabelText(/add a photo/i), file);

    await waitFor(() =>
      expect(api.requestUpload).toHaveBeenCalledWith(
        "prop-1",
        "kitchen.jpg",
        "image/jpeg",
      ),
    );
    // The bytes go to the presigned URL from requestUpload, carrying the file.
    expect(api.uploadToPresignedUrl).toHaveBeenCalledWith(
      "https://s3.example/put/new-kitchen.jpg",
      file,
    );
    // Ordering: the URL must be requested before the PUT is attempted.
    expect(
      api.requestUpload.mock.invocationCallOrder[0],
    ).toBeLessThan(api.uploadToPresignedUrl.mock.invocationCallOrder[0]);
    // And the list is refreshed after the upload so the new photo appears.
    expect(await screen.findByAltText("kitchen.jpg")).toBeInTheDocument();
  });
});

describe("PropertyPhotos — upload failure (Req 4.1)", () => {
  it("surfaces an error and leaves the gallery unchanged when the PUT rejects", async () => {
    const user = userEvent.setup();
    const api = makeApi([photo("p1", "existing.jpg")]);
    api.uploadToPresignedUrl.mockRejectedValue(new Error("S3 refused"));
    render(<PropertyPhotos propertyId="prop-1" api={api} />);

    await screen.findByAltText("existing.jpg");
    const listCallsBefore = api.listPhotos.mock.calls.length;

    await user.upload(screen.getByLabelText(/add a photo/i), jpegFile("kitchen.jpg"));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/couldn't upload/i);
    expect(alert).toHaveTextContent(/kitchen\.jpg/i);

    // The existing photo is still present and no successful refresh occurred.
    expect(screen.getByAltText("existing.jpg")).toBeInTheDocument();
    expect(screen.queryByAltText("kitchen.jpg")).not.toBeInTheDocument();
    expect(api.listPhotos.mock.calls.length).toBe(listCallsBefore);
  });
});

describe("PropertyPhotos — list load error (Req 4.3)", () => {
  it("shows an error with a retry that reloads the gallery on success", async () => {
    const user = userEvent.setup();
    const api = makeApi([photo("p1", "front.jpg")]);
    // First load fails, retry succeeds.
    api.listPhotos
      .mockRejectedValueOnce(new Error("network"))
      .mockImplementation(async () => [photo("p1", "front.jpg")]);

    render(<PropertyPhotos propertyId="prop-1" api={api} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/couldn't load the photos/i);

    const retry = screen.getByRole("button", { name: /retry/i });
    await user.click(retry);

    expect(await screen.findByAltText("front.jpg")).toBeInTheDocument();
    expect(screen.queryByText(/couldn't load the photos/i)).not.toBeInTheDocument();
  });
});

describe("PropertyPhotos — delete keyboard operability (Req 4.4 / 14.4)", () => {
  it("triggers delete when the focused delete button is activated by keyboard", async () => {
    const user = userEvent.setup();
    const api = makeApi([photo("p1", "front.jpg"), photo("p2", "back.png", "image/png")]);
    const confirmDelete = vi.fn(() => true);
    render(
      <PropertyPhotos propertyId="prop-1" api={api} confirmDelete={confirmDelete} />,
    );

    await screen.findByAltText("front.jpg");

    const deleteButton = screen.getByRole("button", { name: /delete front\.jpg/i });
    deleteButton.focus();
    expect(deleteButton).toHaveFocus();

    // Activate purely via the keyboard (Enter), no pointer.
    await user.keyboard("{Enter}");

    expect(confirmDelete).toHaveBeenCalled();
    await waitFor(() =>
      expect(api.deletePhoto).toHaveBeenCalledWith("prop-1", "p1"),
    );
    await waitFor(() =>
      expect(screen.queryByAltText("front.jpg")).not.toBeInTheDocument(),
    );
    expect(screen.getByAltText("back.png")).toBeInTheDocument();
  });
});

beforeEach(() => {
  vi.restoreAllMocks();
});
