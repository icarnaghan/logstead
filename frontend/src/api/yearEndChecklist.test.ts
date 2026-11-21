import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../lib/apiClient";
import { YearEndChecklistApi } from "./yearEndChecklist";

function setup() {
  const client = { get: vi.fn().mockResolvedValue({ ok: true }) };
  const api = new YearEndChecklistApi(client as unknown as ApiClient);
  return { api, client };
}

describe("YearEndChecklistApi", () => {
  it("getChecklist GETs the property route with the taxYear query", async () => {
    const { api, client } = setup();
    const controller = new AbortController();

    const result = await api.getChecklist("p1", 2023, controller.signal);

    expect(result).toEqual({ ok: true });
    const [path, options] = client.get.mock.calls[0];
    expect(path).toBe("/properties/p1/checklist");
    expect(options?.query).toEqual({ taxYear: 2023 });
    expect(options?.signal).toBe(controller.signal);
  });

  it("getChecklist omits the query when no year is given", async () => {
    const { api, client } = setup();

    await api.getChecklist("p1", undefined);

    expect(client.get.mock.calls[0][1]?.query).toBeUndefined();
  });

  it("getPropertySummary GETs the summary route with no query", async () => {
    const { api, client } = setup();

    await api.getPropertySummary("p1");

    const [path, options] = client.get.mock.calls[0];
    expect(path).toBe("/properties/p1/checklist/summary");
    expect(options?.query).toBeUndefined();
  });

  it("getPortfolioSummary sends taxYear when given and omits it otherwise", async () => {
    const { api, client } = setup();

    await api.getPortfolioSummary(2022);
    await api.getPortfolioSummary(null);

    const [path, options] = client.get.mock.calls[0];
    expect(path).toBe("/checklist/summary");
    expect(options?.query).toEqual({ taxYear: 2022 });
    expect(client.get.mock.calls[1][1]?.query).toBeUndefined();
  });
});
