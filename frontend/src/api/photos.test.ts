import { describe, expect, it, vi } from "vitest";
import {
  ALLOWED_IMAGE_TYPES,
  isAllowedImageType,
  PhotosApi,
  type PhotoWithUrl,
  type PresignedUpload,
} from "./photos";

/** Minimal ApiClient double capturing method calls. */
function makeClient(
  overrides: Partial<Pick<PhotosApi, never>> & {
    get?: ReturnType<typeof vi.fn>;
    post?: ReturnType<typeof vi.fn>;
    delete?: ReturnType<typeof vi.fn>;
  } = {},
) {
  return {
    get: overrides.get ?? vi.fn(),
    post: overrides.post ?? vi.fn(),
    delete: overrides.delete ?? vi.fn(),
  };
}

describe("photos api — content type allow-list (Req 4.2)", () => {
  it("accepts exactly the documented image types", () => {
    for (const type of ALLOWED_IMAGE_TYPES) {
      expect(isAllowedImageType(type)).toBe(true);
    }
  });

  it("rejects other types", () => {
    expect(isAllowedImageType("application/pdf")).toBe(false);
    expect(isAllowedImageType("image/gif")).toBe(false);
    expect(isAllowedImageType("text/plain")).toBe(false);
    expect(isAllowedImageType("")).toBe(false);
  });
});

describe("PhotosApi.listPhotos (Req 4.3)", () => {
  it("GETs the property photos path", async () => {
    const payload: PhotoWithUrl[] = [
      {
        photo: {
          id: "p1",
          property_id: "prop-1",
          s3_key: "photos/prop-1/p1/a.jpg",
          content_type: "image/jpeg",
          original_filename: "a.jpg",
          uploaded_at: "2024-01-01T00:00:00Z",
        },
        display_url: "https://s3.example/a.jpg",
      },
    ];
    const get = vi.fn().mockResolvedValue(payload);
    const api = new PhotosApi(makeClient({ get }));

    const result = await api.listPhotos("prop-1");

    expect(get).toHaveBeenCalledWith("/properties/prop-1/photos");
    expect(result).toEqual(payload);
  });
});

describe("PhotosApi.requestUpload (Req 4.1)", () => {
  it("POSTs filename + content_type and returns the presigned upload", async () => {
    const presigned: PresignedUpload = {
      upload_url: "https://s3.example/put",
      photo: {
        id: "p2",
        property_id: "prop-1",
        s3_key: "photos/prop-1/p2/b.png",
        content_type: "image/png",
        original_filename: "b.png",
        uploaded_at: null,
      },
    };
    const post = vi.fn().mockResolvedValue(presigned);
    const api = new PhotosApi(makeClient({ post }));

    const result = await api.requestUpload("prop-1", "b.png", "image/png");

    expect(post).toHaveBeenCalledWith("/properties/prop-1/photos", {
      body: { filename: "b.png", content_type: "image/png" },
    });
    expect(result).toEqual(presigned);
  });
});

describe("PhotosApi.deletePhoto (Req 4.4)", () => {
  it("DELETEs the photo path", async () => {
    const del = vi.fn().mockResolvedValue(undefined);
    const api = new PhotosApi(makeClient({ delete: del }));

    await api.deletePhoto("prop-1", "p1");

    expect(del).toHaveBeenCalledWith("/properties/prop-1/photos/p1");
  });
});

describe("PhotosApi.uploadToPresignedUrl", () => {
  it("PUTs the file body with its content type to the signed URL", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 200 }));
    const api = new PhotosApi(makeClient(), fetchImpl);
    const file = new File(["bytes"], "c.webp", { type: "image/webp" });

    await api.uploadToPresignedUrl("https://s3.example/put", file);

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://s3.example/put");
    expect(init.method).toBe("PUT");
    expect(init.body).toBe(file);
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe(
      "image/webp",
    );
  });

  it("throws when S3 responds with a non-2xx status", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 403 }));
    const api = new PhotosApi(makeClient(), fetchImpl);
    const file = new File(["bytes"], "c.webp", { type: "image/webp" });

    await expect(
      api.uploadToPresignedUrl("https://s3.example/put", file),
    ).rejects.toThrow(/403/);
  });
});
