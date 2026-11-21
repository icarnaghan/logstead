import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/apiClient";
import {
  beginExtraction,
  getExtraction,
  resetScheduleEExtractionClient,
  setScheduleEExtractionClient,
  startExtraction,
  type ExtractionJobView,
} from "./scheduleEExtraction";

/**
 * Unit tests for the Schedule E PDF Extraction API module (task 10.2).
 *
 * Each helper is exercised through the injectable client seam
 * (`setScheduleEExtractionClient`) backed by an injected `fetch`, so no network
 * is touched; we assert the method, path, and snake_case body sent to the
 * backend, and that the snake_case response parses through with money/ids left
 * as strings.
 *
 * Design: Testing Strategy → frontend api; "Route surface + wiring".
 */

/**
 * Build an `ApiClient` whose `fetch` returns the given JSON payload, and a spy
 * we can inspect for the request URL/method/body.
 */
function clientReturning(payload: unknown, status = 200) {
  const fetchImpl = vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit) => {
      const body = payload === null ? null : JSON.stringify(payload);
      return new Response(body, {
        status,
        headers: { "content-type": "application/json" },
      });
    },
  );
  const client = new ApiClient({
    baseUrl: "https://api.test",
    getAuthToken: () => null,
    fetchImpl: fetchImpl as unknown as typeof fetch,
  });
  return { client, fetchImpl };
}

afterEach(() => {
  resetScheduleEExtractionClient();
});

describe("scheduleEExtraction api", () => {
  it("startExtraction posts the snake_case body to /imports/schedule-e/extractions", async () => {
    const response = {
      job_id: "7b1f-abc",
      upload_url: "https://s3.test/signed-put",
    };
    const { client, fetchImpl } = clientReturning(response, 201);
    setScheduleEExtractionClient(client);

    const result = await startExtraction("2023-return.pdf", "application/pdf");

    expect(result).toEqual(response);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.test/imports/schedule-e/extractions");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({
      filename: "2023-return.pdf",
      content_type: "application/pdf",
    });
  });

  it("beginExtraction posts to the encoded {jobId}/start path with no body", async () => {
    const response = { job_id: "7b1f abc", status: "processing" };
    const { client, fetchImpl } = clientReturning(response);
    setScheduleEExtractionClient(client);

    const result = await beginExtraction("7b1f abc");

    expect(result).toEqual(response);
    const [url, init] = fetchImpl.mock.calls[0];
    // The jobId is percent-encoded in the path and `/start` is appended.
    expect(url).toBe(
      "https://api.test/imports/schedule-e/extractions/7b1f%20abc/start",
    );
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeUndefined();
  });

  it("getExtraction GETs the encoded {jobId} path while running", async () => {
    const view = {
      job_id: "7b1f-abc",
      status: "processing",
      outcome: null,
      message: null,
      review_draft: null,
    };
    const { client, fetchImpl } = clientReturning(view);
    setScheduleEExtractionClient(client);

    const result = await getExtraction("7b1f-abc");

    expect(result).toEqual(view);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(
      "https://api.test/imports/schedule-e/extractions/7b1f-abc",
    );
    expect(init?.method).toBe("GET");
  });

  it("getExtraction parses a complete draft, keeping amounts/ids as strings", async () => {
    const view: ExtractionJobView = {
      job_id: "7b1f-abc",
      status: "complete",
      outcome: "draft",
      message: null,
      review_draft: {
        tax_year: 2023,
        tax_year_needs_verification: false,
        columns: [
          {
            address_text: "12 Maple St",
            address_confidence: 97.1,
            suggested_property_id: "1111-prop",
            suggested_property_name: "Maple Duplex",
            mapping_confidence: 0.86,
            lines: [
              {
                schedule_e_line: 3,
                amount: "24000.00",
                needs_verification: false,
                confidence: 98.3,
              },
              {
                schedule_e_line: 14,
                amount: "1875.50",
                needs_verification: true,
                confidence: 42.0,
              },
            ],
          },
        ],
      },
    };
    const { client } = clientReturning(view);
    setScheduleEExtractionClient(client);

    const result = await getExtraction("7b1f-abc");

    expect(result).toEqual(view);
    // Money and ids stay strings end-to-end (never coerced to numbers).
    const [column] = result.review_draft!.columns;
    expect(column.suggested_property_id).toBe("1111-prop");
    expect(column.lines[0].amount).toBe("24000.00");
    expect(typeof column.lines[0].amount).toBe("string");
    expect(typeof column.lines[1].amount).toBe("string");
  });

  it("getExtraction parses the no-Schedule-E-found outcome", async () => {
    const view = {
      job_id: "7b1f-abc",
      status: "complete",
      outcome: "no_schedule_e_found",
      message: "No Schedule E was located in the uploaded document.",
      review_draft: null,
    };
    const { client } = clientReturning(view);
    setScheduleEExtractionClient(client);

    const result = await getExtraction("7b1f-abc");

    expect(result).toEqual(view);
    expect(result.outcome).toBe("no_schedule_e_found");
    expect(result.review_draft).toBeNull();
  });

  it("getExtraction parses the failed outcome", async () => {
    const view = {
      job_id: "7b1f-abc",
      status: "failed",
      outcome: null,
      message: "The document could not be read; a valid PDF is required.",
      review_draft: null,
    };
    const { client } = clientReturning(view);
    setScheduleEExtractionClient(client);

    const result = await getExtraction("7b1f-abc");

    expect(result).toEqual(view);
    expect(result.status).toBe("failed");
  });
});
