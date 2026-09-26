import { describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "./apiClient";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("ApiClient", () => {
  it("attaches the bearer token and base URL to requests", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }));
    const client = new ApiClient({
      baseUrl: "https://api.example.com/",
      getAuthToken: () => "test-token",
      fetchImpl,
    });

    const result = await client.get<{ ok: boolean }>("/properties");

    expect(result).toEqual({ ok: true });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.example.com/properties");
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer test-token",
    );
  });

  it("omits the Authorization header when no token is available", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, {}));
    const client = new ApiClient({
      baseUrl: "https://api.example.com",
      getAuthToken: () => null,
      fetchImpl,
    });

    await client.get("/dashboard");

    const [, init] = fetchImpl.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("serializes JSON bodies and sets the content type", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(201, { id: "1" }));
    const client = new ApiClient({
      baseUrl: "https://api.example.com",
      getAuthToken: () => null,
      fetchImpl,
    });

    await client.post("/properties", { body: { name: "Unit A" } });

    const [, init] = fetchImpl.mock.calls[0];
    expect(init.body).toBe(JSON.stringify({ name: "Unit A" }));
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe(
      "application/json",
    );
  });

  it("appends query parameters", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, []));
    const client = new ApiClient({
      baseUrl: "https://api.example.com",
      getAuthToken: () => null,
      fetchImpl,
    });

    await client.get("/transactions", { query: { taxYear: 2024, skip: undefined } });

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.example.com/transactions?taxYear=2024");
  });

  it("throws a typed ApiError on non-2xx responses", async () => {
    // Return a fresh Response per call so each request reads an unconsumed body.
    const fetchImpl = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(jsonResponse(401, { message: "Unauthorized" })),
      );
    const client = new ApiClient({
      baseUrl: "https://api.example.com",
      getAuthToken: () => null,
      fetchImpl,
    });

    await expect(client.get("/properties")).rejects.toMatchObject({
      status: 401,
      message: "Unauthorized",
    });

    const error = await client.get("/properties").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).isUnauthorized).toBe(true);
  });

  it("invokes onUnauthorized on 401 and still throws the error", async () => {
    const onUnauthorized = vi.fn();
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse(401, { message: "Unauthorized" }));
    const client = new ApiClient({
      baseUrl: "https://api.example.com",
      getAuthToken: () => "expired-token",
      fetchImpl,
      onUnauthorized,
    });

    await expect(client.get("/properties")).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(onUnauthorized.mock.calls[0][0].isUnauthorized).toBe(true);
  });

  it("does not invoke onUnauthorized for non-401 errors", async () => {
    const onUnauthorized = vi.fn();
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse(500, { message: "Server error" }));
    const client = new ApiClient({
      baseUrl: "https://api.example.com",
      getAuthToken: () => null,
      fetchImpl,
      onUnauthorized,
    });

    await expect(client.get("/properties")).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).not.toHaveBeenCalled();
  });
});
