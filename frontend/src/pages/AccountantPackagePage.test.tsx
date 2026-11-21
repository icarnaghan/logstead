import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import AccountantPackagePage from "./AccountantPackagePage";
import type { PackageJobView } from "../api/accountantPackage";
import type { Property } from "../api/properties";
import { latestCompletedTaxYear } from "../lib/taxYears";
import { ThemeProvider } from "../theme/ThemeProvider";

vi.mock("../api/properties", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/properties")>()),
  listProperties: vi.fn().mockResolvedValue([]),
  getEarliestDataYear: vi.fn().mockResolvedValue(null),
}));

const LATEST = latestCompletedTaxYear();

const PROPERTIES = [
  { id: "p1", name: "Maple House" },
  { id: "p2", name: "Oak Flat" },
] as unknown as Property[];

function job(over: Partial<PackageJobView> = {}): PackageJobView {
  return {
    id: "job-1",
    status: "queued",
    tax_year: LATEST,
    property_ids: ["p1", "p2"],
    created_at: "2025-01-01T00:00:00Z",
    finished_at: null,
    message: null,
    size_bytes: null,
    sha256: null,
    file_count: null,
    receipt_count: null,
    skipped_receipt_count: null,
    download_url: null,
    download_expires_in_seconds: null,
    ...over,
  };
}

function complete(over: Partial<PackageJobView> = {}): PackageJobView {
  return job({
    status: "complete",
    size_bytes: 2048,
    sha256: "abc123",
    file_count: 7,
    receipt_count: 3,
    skipped_receipt_count: 0,
    download_url: "https://example.test/pkg.zip",
    download_expires_in_seconds: 900,
    ...over,
  });
}

function setup(api: Partial<Record<string, ReturnType<typeof vi.fn>>> = {}) {
  const fullApi = {
    listPackages: vi.fn().mockResolvedValue({ jobs: [] }),
    createPackage: vi.fn().mockResolvedValue(job()),
    getPackage: vi.fn().mockResolvedValue(complete()),
    deletePackage: vi.fn().mockResolvedValue(undefined),
    ...api,
  };
  render(
    <ThemeProvider>
      <MemoryRouter>
        <AccountantPackagePage
          jobOptions={{ api: fullApi as never, intervalMs: 10 }}
          loadProperties={() => Promise.resolve(PROPERTIES)}
        />
      </MemoryRouter>
    </ThemeProvider>,
  );
  return fullApi;
}

const disclaimer = () => screen.getByRole("note");
const prepareButton = () => screen.getByRole("button", { name: "Prepare package" });

describe("AccountantPackagePage", () => {
  it("shows the idle state with title, contents, disclaimer, and all properties checked", async () => {
    setup();
    expect(
      screen.getByRole("heading", { level: 1, name: "Accountant package" }),
    ).toBeInTheDocument();
    expect(document.title).toContain("Accountant package");
    expect(disclaimer()).toHaveTextContent(/not tax advice/i);
    expect(screen.getByText("What is in the package")).toBeInTheDocument();
    expect(await screen.findByLabelText("Maple House")).toBeChecked();
    expect(screen.getByLabelText("Oak Flat")).toBeChecked();
    expect(screen.getByLabelText("Tax year")).toHaveValue(String(LATEST));
    await waitFor(() => expect(prepareButton()).toBeEnabled());
    expect(await screen.findByText("No package prepared yet.")).toBeInTheDocument();
  });

  it("prepares, shows progress with Prepare disabled, then shows the completed package", async () => {
    const user = userEvent.setup();
    let finish: (v: PackageJobView) => void = () => {};
    const api = setup({
      getPackage: vi.fn().mockReturnValue(
        new Promise<PackageJobView>((resolve) => {
          finish = resolve;
        }),
      ),
    });
    await screen.findByLabelText("Maple House");
    await waitFor(() => expect(prepareButton()).toBeEnabled());
    await user.click(prepareButton());
    expect(api.createPackage).toHaveBeenCalledWith(LATEST, ["p1", "p2"]);
    expect(await screen.findByText(/Waiting to start/)).toBeInTheDocument();
    expect(prepareButton()).toBeDisabled();
    expect(disclaimer()).toBeInTheDocument();
    finish(complete());
    const link = await screen.findByRole("link", { name: "Download package" });
    expect(link).toHaveAttribute("href", "https://example.test/pkg.zip");
    expect(screen.getByText("abc123")).toBeInTheDocument();
    expect(disclaimer()).toBeInTheDocument();
  });

  it("shows the skipped receipts note", async () => {
    setup({
      listPackages: vi
        .fn()
        .mockResolvedValue({ jobs: [complete({ skipped_receipt_count: 2 })] }),
    });
    expect(await screen.findByText(/2 receipts were left out/)).toBeInTheDocument();
    expect(screen.getByText(/manifest\.json/)).toBeInTheDocument();
  });

  it("shows a failed job with the message and retries", async () => {
    const user = userEvent.setup();
    const api = setup({
      listPackages: vi.fn().mockResolvedValue({
        jobs: [job({ status: "failed", message: "Worker gave up" })],
      }),
    });
    expect(await screen.findByText("Worker gave up")).toBeInTheDocument();
    expect(disclaimer()).toBeInTheDocument();
    await waitFor(() => expect(prepareButton()).toBeEnabled());
    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(api.createPackage).toHaveBeenCalledTimes(1);
  });

  it("resumes polling an active job and finishes", async () => {
    let finish: (v: PackageJobView) => void = () => {};
    const api = setup({
      listPackages: vi
        .fn()
        .mockResolvedValue({ jobs: [job({ status: "running" })] }),
      getPackage: vi.fn().mockReturnValue(
        new Promise<PackageJobView>((resolve) => {
          finish = resolve;
        }),
      ),
    });
    expect(await screen.findByText(/Preparing your package/)).toBeInTheDocument();
    expect(prepareButton()).toBeDisabled();
    finish(complete());
    expect(
      await screen.findByRole("link", { name: "Download package" }),
    ).toBeInTheDocument();
    expect(api.getPackage).toHaveBeenCalledWith("job-1", expect.anything());
  });

  it("shows the latest finished job without polling", async () => {
    const api = setup({
      listPackages: vi.fn().mockResolvedValue({ jobs: [complete()] }),
    });
    expect(
      await screen.findByRole("link", { name: "Download package" }),
    ).toBeInTheDocument();
    expect(api.getPackage).not.toHaveBeenCalled();
    expect(disclaimer()).toBeInTheDocument();
  });

  it("deletes a finished package after confirmation", async () => {
    const user = userEvent.setup();
    const api = setup({
      listPackages: vi.fn().mockResolvedValue({ jobs: [complete()] }),
    });
    await user.click(await screen.findByRole("button", { name: "Delete package" }));
    const dialog = await screen.findByRole("alertdialog").catch(() =>
      screen.findByRole("dialog"),
    );
    expect(api.deletePackage).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.deletePackage).toHaveBeenCalledWith("job-1"));
    expect(await screen.findByText("No package prepared yet.")).toBeInTheDocument();
  });

  it("uses the chosen year and selected properties", async () => {
    const user = userEvent.setup();
    const api = setup();
    await user.click(await screen.findByLabelText("Oak Flat"));
    await user.selectOptions(screen.getByLabelText("Tax year"), String(LATEST - 1));
    await waitFor(() => expect(prepareButton()).toBeEnabled());
    await user.click(prepareButton());
    expect(api.createPackage).toHaveBeenCalledWith(LATEST - 1, ["p1"]);
  });
});
