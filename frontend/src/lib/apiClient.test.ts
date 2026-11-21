import { describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError, UnsafeApiPathError } from "./apiClient";

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

  describe("token leakage guard", () => {
    const make = (baseUrl = "https://api.example.com") => {
      const fetchImpl = vi
        .fn()
        .mockImplementation(() => Promise.resolve(jsonResponse(200, {})));
      const client = new ApiClient({
        baseUrl,
        getAuthToken: () => "secret-token",
        fetchImpl,
      });
      return { client, fetchImpl };
    };

    it.each([
      "https://evil.example.net/steal",
      "http://api.example.com/x",
      "HTTPS://evil.example.net",
      "javascript:alert(1)",
      "//evil.example.net/x",
      "///evil.example.net/x",
      "/\\evil.example.net/x",
      "\\\\evil.example.net/x",
      "/../admin",
      "/a/../../b",
      "/a/%2e%2e/b",
      "/a/%2E./b",
      "/a\nb",
    ])("rejects %j without calling fetch", async (path) => {
      const { client, fetchImpl } = make();
      await expect(client.get(path)).rejects.toBeInstanceOf(UnsafeApiPathError);
      expect(fetchImpl).not.toHaveBeenCalled();
    });

    it.each([
      "/properties/a%2Fb/report",
      "/properties/a%5Cb/report",
      "/a/%2E%2E%2Fb",
      "/a/%zz",
    ])("sends encoded path %j unchanged with the bearer", async (path) => {
      const { client, fetchImpl } = make();
      await client.get(path);
      const [url, init] = fetchImpl.mock.calls[0];
      expect(url).toBe(`https://api.example.com${path}`);
      expect(init.headers.Authorization).toBe("Bearer secret-token");
    });

    it("keeps relative paths on the API origin with a trailing-slash base", async () => {
      const { client, fetchImpl } = make("https://api.example.com/v1/");
      await client.get("properties/1", { query: { a: 1 } });
      await client.get("/properties?x=1", { query: { a: 1 } });
      expect(fetchImpl.mock.calls[0][0]).toBe(
        "https://api.example.com/v1/properties/1?a=1",
      );
      expect(fetchImpl.mock.calls[1][0]).toBe(
        "https://api.example.com/v1/properties?x=1&a=1",
      );
      const [, init] = fetchImpl.mock.calls[0];
      expect(init.headers.Authorization).toBe("Bearer secret-token");
    });

    it("allows same-origin relative URLs when no base URL is configured", async () => {
      const { client, fetchImpl } = make("");
      await client.get("/properties");
      expect(fetchImpl.mock.calls[0][0]).toBe("/properties");
      await expect(client.get("//evil.example.net")).rejects.toBeInstanceOf(
        UnsafeApiPathError,
      );
    });
  });
});
