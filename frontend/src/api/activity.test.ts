import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../lib/apiClient";
import { ActivityApi } from "./activity";

function setup() {
  const client = {
    get: vi.fn().mockResolvedValue({ events: [], next_cursor: null }),
    post: vi.fn().mockResolvedValue({ record_id: "r2" }),
  };
  return { api: new ActivityApi(client as unknown as ApiClient), client };
}

describe("ActivityApi", () => {
  it("list GETs /activity and omits unset filters", async () => {
    const { api, client } = setup();
    await api.list({ limit: 50, entity: null, cursor: "" });
    expect(client.get).toHaveBeenCalledWith("/activity", {
      query: {
        limit: 50,
        cursor: undefined,
        entity: undefined,
        action: undefined,
        propertyId: undefined,
      },
      signal: undefined,
    });
  });

  it("list passes every filter", async () => {
    const { api, client } = setup();
    await api.list({
      limit: 10,
      cursor: "c1",
      entity: "asset",
      action: "delete",
      propertyId: "p1",
    });
    expect(client.get.mock.calls[0][1].query).toEqual({
      limit: 10,
      cursor: "c1",
      entity: "asset",
      action: "delete",
      propertyId: "p1",
    });
  });

  it("listForProperty encodes the property id in the path", async () => {
    const { api, client } = setup();
    await api.listForProperty("a/b", { limit: 5 });
    expect(client.get.mock.calls[0][0]).toBe("/properties/a%2Fb/activity");
    expect(client.get.mock.calls[0][1].query.limit).toBe(5);
  });

  it("restore POSTs to the restore route and returns the new id", async () => {
    const { api, client } = setup();
    const out = await api.restore("p1", "123.abc");
    expect(client.post).toHaveBeenCalledWith(
      "/properties/p1/activity/123.abc/restore",
      { signal: undefined },
    );
    expect(out.record_id).toBe("r2");
  });
});
