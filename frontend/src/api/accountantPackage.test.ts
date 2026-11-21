import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/apiClient";
import { AccountantPackageApi, type PackageJobView } from "./accountantPackage";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function apiWith(fetchImpl: typeof fetch): AccountantPackageApi {
  return new AccountantPackageApi(
    new ApiClient({
      baseUrl: "https://api.example.com",
      getAuthToken: () => "t",
      fetchImpl,
    }),
  );
}

const JOB: PackageJobView = {
  id: "job-1",
  status: "queued",
  tax_year: 2024,
  property_ids: ["p1"],
  created_at: "2025-01-15T14:03:22+00:00",
  finished_at: null,
  message: null,
  size_bytes: null,
  sha256: null,
  file_count: null,
  receipt_count: null,
  skipped_receipt_count: null,
  download_url: null,
  download_expires_in_seconds: null,
};

describe("AccountantPackageApi", () => {
  it("createPackage POSTs tax_year and property_ids", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(202, JOB));

    const job = await apiWith(fetchImpl).createPackage(2024, ["p1"]);

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.example.com/accountant-packages");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      tax_year: 2024,
      property_ids: ["p1"],
    });
    expect(job.id).toBe("job-1");
  });

  it("createPackage omits property_ids when none are given", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(202, JOB));

    await apiWith(fetchImpl).createPackage(2024);

    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual({
      tax_year: 2024,
    });
  });

  it("listPackages GETs the collection", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { jobs: [JOB] }));

    const list = await apiWith(fetchImpl).listPackages();

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.example.com/accountant-packages");
    expect(init.method).toBe("GET");
    expect(list.jobs).toHaveLength(1);
  });

  it("getPackage GETs one job with the id encoded", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, JOB));

    await apiWith(fetchImpl).getPackage("a/b");

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.example.com/accountant-packages/a%2Fb");
    expect(init.method).toBe("GET");
  });

  it("deletePackage sends DELETE to the job path", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, {}));

    await apiWith(fetchImpl).deletePackage("job-1");

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.example.com/accountant-packages/job-1");
    expect(init.method).toBe("DELETE");
  });
});
