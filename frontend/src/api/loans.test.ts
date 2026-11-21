import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/apiClient";
import {
  clearInterestOverride,
  createLoan,
  deleteLoan,
  getLine12Impact,
  getLoan,
  getLoanSchedule,
  listLoans,
  setInterestOverride,
  updateLoan,
  type Loan,
  type LoanInput,
} from "./loans";

/**
 * Tests for the mortgage loans API module. An {@link ApiClient} backed by a
 * fake `fetch` exercises the real request-building / JSON-parsing path with
 * no network calls.
 */

function makeFetch(handler: (url: string, init: RequestInit) => Response) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
    Promise.resolve(handler(String(input), init ?? {})),
  );
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function clientFor(fetchImpl: ReturnType<typeof makeFetch>): ApiClient {
  return new ApiClient({ baseUrl: "https://api.test", fetchImpl });
}

const input: LoanInput = {
  description: "Primary mortgage",
  annual_interest_rate: "6.8750",
  monthly_payment: "1970.79",
  anchor_balance: "214500.00",
  anchor_date: "2025-06-01",
  extra_principal: "100.00",
  payoff_date: null,
  original_principal: "300000.00",
  closing_date: null,
  include_in_report: true,
};

const loan: Loan = {
  id: "l1",
  property_id: "p1",
  ...input,
  interest_overrides: { "2024": "7010.12" },
  remaining_payments: 148,
  next_payment_date: "2025-07-01",
  projected_payoff_date: "2037-10-01",
  payoff_balance: null,
  status: "active",
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
};

describe("loans api module", () => {
  it("lists loans via GET /properties/{id}/loans", async () => {
    const fetchImpl = makeFetch((url, init) => {
      expect(url).toBe("https://api.test/properties/p1/loans");
      expect(init.method ?? "GET").toBe("GET");
      return jsonResponse(200, [loan]);
    });

    const result = await listLoans("p1", clientFor(fetchImpl));
    expect(result).toEqual([loan]);
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("creates a loan via POST with money and rate kept as strings", async () => {
    const fetchImpl = makeFetch((url, init) => {
      expect(url).toBe("https://api.test/properties/p1/loans");
      expect(init.method).toBe("POST");
      const body = JSON.parse(String(init.body));
      expect(body).toEqual(input);
      expect(typeof body.monthly_payment).toBe("string");
      expect(typeof body.anchor_balance).toBe("string");
      expect(typeof body.anchor_date).toBe("string");
      expect(typeof body.annual_interest_rate).toBe("string");
      expect(typeof body.extra_principal).toBe("string");
      return jsonResponse(201, loan);
    });

    const result = await createLoan("p1", input, clientFor(fetchImpl));
    expect(result).toEqual(loan);
    expect(typeof result.anchor_balance).toBe("string");
    expect(typeof result.annual_interest_rate).toBe("string");
    expect(typeof result.remaining_payments).toBe("number");
  });

  it("accepts an override-only yearly rollup with a null ending balance", async () => {
    const schedule = {
      loan_id: "l1",
      estimate: true,
      payoff_balance: null,
      payments: [],
      yearly: [
        {
          tax_year: 2023,
          payments: 0,
          interest: "20650.12",
          estimated_interest: "0.00",
          interest_override: "20650.12",
          variance: "20650.12",
          principal: "0.00",
          total_paid: "0.00",
          ending_balance: null,
        },
      ],
    };
    const fetchImpl = makeFetch(() => jsonResponse(200, schedule));

    const result = await getLoanSchedule("p1", "l1", clientFor(fetchImpl));
    expect(result.yearly[0].ending_balance).toBeNull();
  });

  it("gets a single loan via GET /properties/{id}/loans/{loanId}", async () => {
    const fetchImpl = makeFetch((url) => {
      expect(url).toBe("https://api.test/properties/p1/loans/l1");
      return jsonResponse(200, loan);
    });

    expect(await getLoan("p1", "l1", clientFor(fetchImpl))).toEqual(loan);
  });

  it("updates a loan via PUT with the full input body", async () => {
    const fetchImpl = makeFetch((url, init) => {
      expect(url).toBe("https://api.test/properties/p1/loans/l1");
      expect(init.method).toBe("PUT");
      expect(JSON.parse(String(init.body))).toEqual(input);
      return jsonResponse(200, loan);
    });

    expect(await updateLoan("p1", "l1", input, clientFor(fetchImpl))).toEqual(
      loan,
    );
  });

  it("deletes a loan via DELETE", async () => {
    const fetchImpl = makeFetch((url, init) => {
      expect(url).toBe("https://api.test/properties/p1/loans/l1");
      expect(init.method).toBe("DELETE");
      return new Response(null, { status: 204 });
    });

    // The ApiClient yields no payload for a 204 response.
    await expect(
      deleteLoan("p1", "l1", clientFor(fetchImpl)),
    ).resolves.toBeNull();
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("fetches a schedule via GET .../schedule and keeps strings", async () => {
    const schedule = {
      loan_id: "l1",
      estimate: false,
      payoff_balance: null,
      payments: [
        {
          number: 1,
          date: "2024-02-01",
          payment: "1742.30",
          interest: "1432.29",
          principal: "310.01",
          balance: "249689.99",
        },
      ],
      yearly: [],
    };
    const fetchImpl = makeFetch((url) => {
      expect(url).toBe("https://api.test/properties/p1/loans/l1/schedule");
      return jsonResponse(200, schedule);
    });

    const result = await getLoanSchedule("p1", "l1", clientFor(fetchImpl));
    expect(result).toEqual(schedule);
    expect(typeof result.payments[0].balance).toBe("string");
  });

  it("sets an interest override via PUT with a string interest body", async () => {
    const rollup = { tax_year: 2024, interest: "7010.12" };
    const fetchImpl = makeFetch((url, init) => {
      expect(url).toBe(
        "https://api.test/properties/p1/loans/l1/interest-overrides/2024",
      );
      expect(init.method).toBe("PUT");
      const body = JSON.parse(String(init.body));
      expect(body).toEqual({ interest: "7010.12" });
      expect(typeof body.interest).toBe("string");
      return jsonResponse(200, rollup);
    });

    const result = await setInterestOverride(
      "p1",
      "l1",
      2024,
      "7010.12",
      clientFor(fetchImpl),
    );
    expect(result).toEqual(rollup);
  });

  it("clears an interest override via DELETE", async () => {
    const rollup = { tax_year: 2024, interest: "6900.00" };
    const fetchImpl = makeFetch((url, init) => {
      expect(url).toBe(
        "https://api.test/properties/p1/loans/l1/interest-overrides/2024",
      );
      expect(init.method).toBe("DELETE");
      return jsonResponse(200, rollup);
    });

    expect(
      await clearInterestOverride("p1", "l1", 2024, clientFor(fetchImpl)),
    ).toEqual(rollup);
  });

  it("fetches Line 12 impact via GET .../line-12-impact", async () => {
    const impact = [
      {
        tax_year: 2024,
        loan_interest: "7010.12",
        superseded_manual_interest: { amount: "6000.00", count: 2 },
      },
    ];
    const fetchImpl = makeFetch((url) => {
      expect(url).toBe("https://api.test/properties/p1/loans/line-12-impact");
      return jsonResponse(200, impact);
    });

    const result = await getLine12Impact("p1", clientFor(fetchImpl));
    expect(result).toEqual(impact);
    expect(typeof result[0].superseded_manual_interest.amount).toBe("string");
  });

  it("URL-encodes property and loan ids", async () => {
    const urls: string[] = [];
    const fetchImpl = makeFetch((url) => {
      urls.push(url);
      return jsonResponse(200, loan);
    });
    const client = clientFor(fetchImpl);

    await getLoan("p/1 a", "l?x#y", client);
    await listLoans("p/1 a", client);

    expect(urls[0]).toBe(
      "https://api.test/properties/p%2F1%20a/loans/l%3Fx%23y",
    );
    expect(urls[1]).toBe("https://api.test/properties/p%2F1%20a/loans");
  });

  it("propagates API errors as ApiError", async () => {
    const fetchImpl = makeFetch(() =>
      jsonResponse(404, { error: "not_found", message: "Loan not found." }),
    );

    await expect(
      getLoan("p1", "missing", clientFor(fetchImpl)),
    ).rejects.toMatchObject({ status: 404, message: "Loan not found." });
  });
});
