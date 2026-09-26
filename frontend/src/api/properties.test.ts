import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/apiClient";
import {
  createProperty,
  deleteProperty,
  enrichAddress,
  fetchUnitAddresses,
  getPropertyNote,
  listProperties,
  resetPropertiesClient,
  setPropertiesClient,
  setPropertyNote,
  suggestAddresses,
  type Property,
} from "./properties";

/**
 * Tests for the feature-scoped Properties API module.
 *
 * These inject an {@link ApiClient} backed by a fake `fetch` so the real
 * request-building / JSON-parsing path is exercised without hitting the
 * network (never any live calls).
 */

function makeFetch(handler: (url: string, init: RequestInit) => Response) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
    Promise.resolve(handler(String(input), init ?? {})),
  );
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === null ? "" : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  resetPropertiesClient();
  vi.restoreAllMocks();
});

describe("properties api module", () => {
  it("lists properties via GET /properties", async () => {
    const property: Property = {
      id: "p1",
      user_id: "u1",
      name: "Maple Duplex",
      address_text: "1 Maple St",
      property_type: "single_family",
    };
    const fetchImpl = makeFetch((url) => {
      expect(url).toMatch(/\/properties$/);
      return jsonResponse(200, [property]);
    });
    setPropertiesClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));

    const result = await listProperties();
    expect(result).toEqual([property]);
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("creates a property via POST /properties with a JSON body", async () => {
    const created: Property = {
      id: "p2",
      user_id: "u1",
      name: "Oak House",
      address_text: "2 Oak Ave",
    };
    const fetchImpl = makeFetch((_url, init) => {
      expect(init.method).toBe("POST");
      expect(JSON.parse(String(init.body))).toEqual({
        name: "Oak House",
        address_text: "2 Oak Ave",
      });
      return jsonResponse(201, created);
    });
    setPropertiesClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));

    const result = await createProperty({
      name: "Oak House",
      address_text: "2 Oak Ave",
    });
    expect(result).toEqual(created);
  });

  it("suggests addresses via GET /addresses?q=", async () => {
    const fetchImpl = makeFetch((url) => {
      expect(url).toContain("/addresses?q=1+Ma");
      return jsonResponse(200, [{ formatted_address: "1 Maple St" }]);
    });
    setPropertiesClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));

    const result = await suggestAddresses("1 Ma");
    expect(result[0].formatted_address).toBe("1 Maple St");
  });

  it("fetches unit addresses via GET /addresses/units?address=", async () => {
    const fetchImpl = makeFetch((url) => {
      expect(url).toContain("/addresses/units?address=1+Maple+St");
      return jsonResponse(200, [
        { formatted_address: "1 Maple St Unit A", provider_place_id: "u-a" },
      ]);
    });
    setPropertiesClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));

    const result = await fetchUnitAddresses("1 Maple St");
    expect(result[0].formatted_address).toBe("1 Maple St Unit A");
    expect(result[0].provider_place_id).toBe("u-a");
  });

  it("enriches an address via POST /properties/enrich", async () => {
    const fetchImpl = makeFetch((url, init) => {
      expect(url).toMatch(/\/properties\/enrich$/);
      expect(JSON.parse(String(init.body))).toEqual({ address: "1 Maple St" });
      return jsonResponse(200, { status: "found", details: { bedrooms: 3 } });
    });
    setPropertiesClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));

    const result = await enrichAddress("1 Maple St");
    expect(result.status).toBe("found");
    expect(result.details?.bedrooms).toBe(3);
  });

  it("fetches a property note via GET /properties/{id}/notes and returns text", async () => {
    const fetchImpl = makeFetch((url, init) => {
      expect(url).toMatch(/\/properties\/p1\/notes$/);
      expect(init.method ?? "GET").toBe("GET");
      return jsonResponse(200, { text: "Roof replaced 2023" });
    });
    setPropertiesClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));

    const result = await getPropertyNote("p1");
    expect(result).toBe("Roof replaced 2023");
  });

  it("saves a property note via PUT /properties/{id}/notes and returns the saved text", async () => {
    const fetchImpl = makeFetch((url, init) => {
      expect(url).toMatch(/\/properties\/p1\/notes$/);
      expect(init.method).toBe("PUT");
      expect(JSON.parse(String(init.body))).toEqual({ text: "New note" });
      return jsonResponse(200, { text: "New note" });
    });
    setPropertiesClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));

    const result = await setPropertyNote("p1", "New note");
    expect(result).toBe("New note");
  });

  it("propagates a 409 conflict from a guarded delete as an ApiError", async () => {
    const fetchImpl = makeFetch(() =>
      jsonResponse(409, {
        error: "conflict",
        message: "Remove associated records first.",
      }),
    );
    setPropertiesClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));

    await expect(deleteProperty("p1")).rejects.toMatchObject({
      status: 409,
      message: "Remove associated records first.",
    });
  });
});
