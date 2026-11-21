import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../lib/apiClient";
import {
  CarryforwardApi,
  type ReconciliationSummary,
} from "./carryforward";

/**
 * Build a {@link CarryforwardApi} over a fake {@link ApiClient} whose
 * `get`/`put`/`delete` are vitest spies. The module is transport-only, so the
 * fake lets us assert exactly which route, method, and body each call targets
 * without a network. Only the methods the API module touches are stubbed; the
 * cast keeps the fake structurally compatible with `ApiClient`.
 */
function apiWithFakeClient(overrides?: {
  getResult?: unknown;
}) {
  const client = {
    get: vi.fn().mockResolvedValue(overrides?.getResult ?? null),
    put: vi.fn().mockResolvedValue(undefined),
    delete: vi.fn().mockResolvedValue(undefined),
  };
  const api = new CarryforwardApi(client as unknown as ApiClient);
  return { api, client };
}

describe("CarryforwardApi", () => {
  it("getReconciliation GETs /carryforward with no query and returns the summary", async () => {
    const summary: ReconciliationSummary = {
      years: [
        {
          tax_year: 2023,
          schedule_e_net: "-125.00",
          expected_carry_in: "0.00",
          expected_carryforward: "125.00",
          reported_carryforward: null,
          allowed_loss: "0.00",
          fully_allowed: false,
          status: "unreported",
          drift: null,
          carried_from_year: null,
        },
      ],
      opening_balance: "0.00",
      has_data: true,
      next_year: 2024,
      next_year_expected_carry_in: "125.00",
      status_tolerance: "2.00",
    };
    const { api, client } = apiWithFakeClient({ getResult: summary });

    const result = await api.getReconciliation();

    expect(client.get).toHaveBeenCalledTimes(1);
    const [path, options] = client.get.mock.calls[0];
    expect(path).toBe("/carryforward");
    // No query is sent — the series spans every Data_Year on the backend.
    expect(options?.query).toBeUndefined();
    expect(result).toEqual(summary);
    // Feature: carryforward-carry-in-semantics, Req 7.7: new fields round-trip.
    expect(result.years[0].expected_carry_in).toBe("0.00");
    expect(result.next_year).toBe(2024);
    expect(result.next_year_expected_carry_in).toBe("125.00");
    // Feature: carryforward-tolerance-and-year-range, Req 4.5: tolerance round-trips.
    expect(result.status_tolerance).toBe("2.00");
  });

  // Feature: carryforward-chain-status, Req 6.6
  it("getReconciliation round-trips a carried year with drift and carried_from_year", async () => {
    const summary: ReconciliationSummary = {
      years: [
        {
          tax_year: 2016,
          schedule_e_net: "-1000.00",
          expected_carry_in: "12000.00",
          expected_carryforward: "13000.00",
          reported_carryforward: "8000.00",
          allowed_loss: "0.00",
          fully_allowed: false,
          status: "carried",
          drift: "-4000.00",
          carried_from_year: 2015,
        },
      ],
      opening_balance: "0.00",
      has_data: true,
      next_year: 2017,
      next_year_expected_carry_in: "13000.00",
      status_tolerance: "2.00",
    };
    const { api } = apiWithFakeClient({ getResult: summary });

    const result = await api.getReconciliation();

    expect(result.years[0].status).toBe("carried");
    expect(result.years[0].drift).toBe("-4000.00");
    expect(result.years[0].carried_from_year).toBe(2015);
    expect(result).toEqual(summary);
  });

  it("getReconciliation passes the AbortSignal through to the client", async () => {
    const { api, client } = apiWithFakeClient();
    const controller = new AbortController();

    await api.getReconciliation(controller.signal);

    const [, options] = client.get.mock.calls[0];
    expect(options?.signal).toBe(controller.signal);
  });

  it("setReported PUTs /carryforward/years/{year} with an { amount } body", async () => {
    const { api, client } = apiWithFakeClient();

    await api.setReported(2024, "500.00");

    expect(client.put).toHaveBeenCalledTimes(1);
    const [path, options] = client.put.mock.calls[0];
    expect(path).toBe("/carryforward/years/2024");
    expect(options?.body).toEqual({ amount: "500.00" });
  });

  it("setReported passes the AbortSignal through to the client", async () => {
    const { api, client } = apiWithFakeClient();
    const controller = new AbortController();

    await api.setReported(2024, "500.00", controller.signal);

    const [, options] = client.put.mock.calls[0];
    expect(options?.signal).toBe(controller.signal);
  });

  // Feature: carryforward-allowed-loss, Req 1.6, 6.4
  it("setYear PUTs /carryforward/years/{year} with only an allowed_loss field", async () => {
    const { api, client } = apiWithFakeClient();

    await api.setYear(2010, { allowed_loss: "758.00" });

    expect(client.put).toHaveBeenCalledTimes(1);
    const [path, options] = client.put.mock.calls[0];
    expect(path).toBe("/carryforward/years/2010");
    // Only the keys present in the patch are sent — omitted keys stay untouched.
    expect(options?.body).toEqual({ allowed_loss: "758.00" });
  });

  // Feature: carryforward-allowed-loss, Req 1.6, 6.4
  it("setYear sends exactly the present fields when several are supplied", async () => {
    const { api, client } = apiWithFakeClient();

    await api.setYear(2010, { amount: "0.00", fully_allowed: true });

    const [path, options] = client.put.mock.calls[0];
    expect(path).toBe("/carryforward/years/2010");
    // `allowed_loss` was omitted from the patch, so it is absent from the body.
    expect(options?.body).toEqual({ amount: "0.00", fully_allowed: true });
  });

  // Feature: carryforward-allowed-loss, Req 1.6, 6.4
  it("setYear passes the AbortSignal through to the client", async () => {
    const { api, client } = apiWithFakeClient();
    const controller = new AbortController();

    await api.setYear(2010, { allowed_loss: "758.00" }, controller.signal);

    const [, options] = client.put.mock.calls[0];
    expect(options?.signal).toBe(controller.signal);
  });

  // Feature: carryforward-allowed-loss, Req 1.6, 6.4
  it("setAllowedLoss PUTs the year route with an { allowed_loss } body", async () => {
    const { api, client } = apiWithFakeClient();

    await api.setAllowedLoss(2010, "758.00");

    expect(client.put).toHaveBeenCalledTimes(1);
    const [path, options] = client.put.mock.calls[0];
    // Same PUT route as setReported — no new backend route for allowed data.
    expect(path).toBe("/carryforward/years/2010");
    // Type-level: `allowed_loss` is a money string here.
    expect(options?.body).toEqual({ allowed_loss: "758.00" });
  });

  // Feature: carryforward-allowed-loss, Req 1.6, 6.4
  it("setAllowedLoss passes the AbortSignal through to the client", async () => {
    const { api, client } = apiWithFakeClient();
    const controller = new AbortController();

    await api.setAllowedLoss(2010, "758.00", controller.signal);

    const [, options] = client.put.mock.calls[0];
    expect(options?.signal).toBe(controller.signal);
  });

  // Feature: carryforward-allowed-loss, Req 1.6, 6.4
  it("clearAllowedLoss PUTs the year route with { allowed_loss: null }", async () => {
    const { api, client } = apiWithFakeClient();

    await api.clearAllowedLoss(2010);

    expect(client.put).toHaveBeenCalledTimes(1);
    const [path, options] = client.put.mock.calls[0];
    expect(path).toBe("/carryforward/years/2010");
    // Explicit null clears Allowed_Loss while leaving the year's other fields.
    // Type-level: `allowed_loss` accepts `null` as well as a string.
    expect(options?.body).toEqual({ allowed_loss: null });
  });

  // Feature: carryforward-allowed-loss, Req 1.6, 6.4
  it("setFullyAllowed PUTs the year route with the boolean flag", async () => {
    const { api, client } = apiWithFakeClient();

    await api.setFullyAllowed(2010, true);

    expect(client.put).toHaveBeenCalledTimes(1);
    const [onPath, onOptions] = client.put.mock.calls[0];
    expect(onPath).toBe("/carryforward/years/2010");
    // Type-level: `fully_allowed` is a boolean.
    expect(onOptions?.body).toEqual({ fully_allowed: true });

    await api.setFullyAllowed(2010, false);

    const [offPath, offOptions] = client.put.mock.calls[1];
    expect(offPath).toBe("/carryforward/years/2010");
    expect(offOptions?.body).toEqual({ fully_allowed: false });
  });

  // Feature: carryforward-allowed-loss, Req 1.6, 6.4
  it("setFullyAllowed passes the AbortSignal through to the client", async () => {
    const { api, client } = apiWithFakeClient();
    const controller = new AbortController();

    await api.setFullyAllowed(2010, true, controller.signal);

    const [, options] = client.put.mock.calls[0];
    expect(options?.signal).toBe(controller.signal);
  });

  // Feature: carryforward-allowed-loss, Req 1.6, 6.4
  it("setReported still routes through setYear with an { amount } body", async () => {
    const { api, client } = apiWithFakeClient();

    await api.setReported(2010, "500.00");

    expect(client.put).toHaveBeenCalledTimes(1);
    const [path, options] = client.put.mock.calls[0];
    expect(path).toBe("/carryforward/years/2010");
    expect(options?.body).toEqual({ amount: "500.00" });
  });

  it("clearReported DELETEs /carryforward/years/{year}", async () => {
    const { api, client } = apiWithFakeClient();

    await api.clearReported(2022);

    expect(client.delete).toHaveBeenCalledTimes(1);
    const [path] = client.delete.mock.calls[0];
    expect(path).toBe("/carryforward/years/2022");
  });

  it("clearReported passes the AbortSignal through to the client", async () => {
    const { api, client } = apiWithFakeClient();
    const controller = new AbortController();

    await api.clearReported(2022, controller.signal);

    const [, options] = client.delete.mock.calls[0];
    expect(options?.signal).toBe(controller.signal);
  });

  it("setOpeningBalance PUTs /carryforward/opening-balance with an { amount } body", async () => {
    const { api, client } = apiWithFakeClient();

    await api.setOpeningBalance("1000.00");

    expect(client.put).toHaveBeenCalledTimes(1);
    const [path, options] = client.put.mock.calls[0];
    expect(path).toBe("/carryforward/opening-balance");
    expect(options?.body).toEqual({ amount: "1000.00" });
  });

  it("setOpeningBalance passes the AbortSignal through to the client", async () => {
    const { api, client } = apiWithFakeClient();
    const controller = new AbortController();

    await api.setOpeningBalance("1000.00", controller.signal);

    const [, options] = client.put.mock.calls[0];
    expect(options?.signal).toBe(controller.signal);
  });

  it("types money fields as strings and tax_year as a number", async () => {
    const summary: ReconciliationSummary = {
      years: [
        {
          tax_year: 2023,
          schedule_e_net: "-125.00",
          expected_carry_in: "0.00",
          expected_carryforward: "125.00",
          reported_carryforward: "0.00",
          allowed_loss: "0.00",
          fully_allowed: false,
          status: "ok",
          drift: "0.00",
          carried_from_year: null,
        },
      ],
      opening_balance: "0.00",
      has_data: true,
      next_year: 2024,
      next_year_expected_carry_in: "125.00",
      status_tolerance: "2.00",
    };
    const { api } = apiWithFakeClient({ getResult: summary });

    const result = await api.getReconciliation();

    // Type-level: money fields are declared as `string`. These assignments
    // only compile if the interfaces type them as strings, and the runtime
    // checks confirm the values arrive as strings.
    const year = result.years[0];
    const scheduleENet: string = year.schedule_e_net;
    const expected: string = year.expected_carryforward;
    // `reported_carryforward` is `string | null`; narrow before the assignment.
    const reported: string = year.reported_carryforward ?? "";
    const opening: string = result.opening_balance;
    expect(typeof scheduleENet).toBe("string");
    expect(typeof expected).toBe("string");
    expect(typeof reported).toBe("string");
    expect(typeof opening).toBe("string");
    // `tax_year` stays a number — the one non-string field on a ReconciledYear.
    const taxYear: number = year.tax_year;
    expect(typeof taxYear).toBe("number");
  });
});
