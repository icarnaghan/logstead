import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { ToastProvider } from "../components/ui";
import { ThemeProvider } from "../theme/ThemeProvider";

/**
 * Routing tests for the Imports section (spec modal-forms-and-tabbed-imports,
 * task 2.4). Renders the real route table (`App` → `ImportsLayout` → tab
 * pages) in a `MemoryRouter`; only the network-facing API modules are mocked.
 */

// The manual form lists properties on mount; resolve empty so no network is hit.
vi.mock("../api/properties", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/properties")>()),
  listProperties: vi.fn().mockResolvedValue([]),
  getEarliestDataYear: vi.fn().mockResolvedValue(null),
}));

// The PDF tab's upload + poll calls. A failed job surfaces the manual-form link.
vi.mock("../api/scheduleEExtraction", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/scheduleEExtraction")>()),
  startExtraction: vi
    .fn()
    .mockResolvedValue({ job_id: "job-1", upload_url: "https://s3/put" }),
  uploadToPresignedUrl: vi.fn().mockResolvedValue(undefined),
  beginExtraction: vi
    .fn()
    .mockResolvedValue({ job_id: "job-1", status: "processing" }),
  getExtraction: vi.fn().mockResolvedValue({
    job_id: "job-1",
    status: "failed",
    outcome: null,
    message: "a valid PDF is required",
    review_draft: null,
  }),
}));

function Harness() {
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <>
      <button type="button" onClick={() => navigate(-1)}>
        history-back
      </button>
      <output data-testid="pathname">{location.pathname}</output>
    </>
  );
}

function renderAt(path: string) {
  return render(
    <ThemeProvider><ToastProvider>
      <MemoryRouter initialEntries={[path]}>
        <Harness />
        <App />
      </MemoryRouter>
    </ToastProvider></ThemeProvider>,
  );
}

const MANUAL_MARKER = /backfill a prior year's schedule e/i;
const PDF_MARKER = /upload only your schedule e pages/i;

function importTabs() {
  return screen.getByRole("navigation", { name: /import methods/i });
}

function tab(name: RegExp) {
  return within(importTabs()).getByRole("link", { name });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Imports section routing", () => {
  it("redirects /imports to /imports/schedule-e", async () => {
    renderAt("/imports");

    await waitFor(() =>
      expect(screen.getByTestId("pathname")).toHaveTextContent(
        "/imports/schedule-e",
      ),
    );
    expect(screen.getByTestId("pathname").textContent).toBe(
      "/imports/schedule-e",
    );
    expect(screen.getByText(MANUAL_MARKER)).toBeInTheDocument();
    expect(tab(/enter manually/i)).toHaveAttribute("aria-current", "page");
  });

  it("shows the Manual tab and its content at /imports/schedule-e", () => {
    renderAt("/imports/schedule-e");

    expect(tab(/enter manually/i)).toHaveAttribute("aria-current", "page");
    expect(tab(/upload pdf/i)).not.toHaveAttribute("aria-current");
    expect(screen.getByText(MANUAL_MARKER)).toBeInTheDocument();
    expect(screen.queryByText(PDF_MARKER)).not.toBeInTheDocument();
  });

  it("shows the PDF tab and its content at /imports/schedule-e/extract", () => {
    renderAt("/imports/schedule-e/extract");

    expect(tab(/upload pdf/i)).toHaveAttribute("aria-current", "page");
    expect(tab(/enter manually/i)).not.toHaveAttribute("aria-current");
    expect(screen.getByText(PDF_MARKER)).toBeInTheDocument();
    expect(screen.queryByText(MANUAL_MARKER)).not.toBeInTheDocument();
  });

  it("renders the page heading above the tabs", () => {
    renderAt("/imports/schedule-e");

    const heading = screen.getByRole("heading", {
      level: 1,
      name: "Import Schedule E",
    });
    expect(
      heading.compareDocumentPosition(importTabs()) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("shows the destination tab in its initial state and discards typed entries", async () => {
    const user = userEvent.setup();
    renderAt("/imports/schedule-e");

    const taxYear = screen.getByLabelText(/^tax year$/i) as HTMLInputElement;
    const initial = taxYear.value;
    await user.clear(taxYear);
    await user.type(taxYear, "1999");
    expect(taxYear).toHaveValue(1999);

    await user.click(tab(/upload pdf/i));
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.getByText(PDF_MARKER)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^tax year$/i)).not.toBeInTheDocument();

    await user.click(tab(/enter manually/i));
    expect(screen.getByLabelText(/^tax year$/i)).toHaveValue(Number(initial));
    expect(screen.getByLabelText(/^tax year$/i)).not.toHaveValue(1999);
  });

  it("resets the PDF tab to its initial state after switching away and back", async () => {
    const user = userEvent.setup();
    renderAt("/imports/schedule-e/extract");

    await user.upload(
      screen.getByLabelText(/choose your schedule e pages/i),
      new File(["%PDF-1.4"], "return.pdf", { type: "application/pdf" }),
    );
    expect(
      await screen.findByRole("link", { name: /enter your schedule e manually/i }),
    ).toBeInTheDocument();

    await user.click(tab(/enter manually/i));
    await user.click(tab(/upload pdf/i));

    expect(
      screen.queryByRole("link", { name: /enter your schedule e manually/i }),
    ).not.toBeInTheDocument();
  });

  it("returns to the previous tab on history back", async () => {
    const user = userEvent.setup();
    renderAt("/imports/schedule-e");

    await user.click(tab(/upload pdf/i));
    expect(screen.getByTestId("pathname")).toHaveTextContent(
      "/imports/schedule-e/extract",
    );

    await user.click(screen.getByRole("button", { name: "history-back" }));

    expect(screen.getByTestId("pathname").textContent).toBe(
      "/imports/schedule-e",
    );
    expect(tab(/enter manually/i)).toHaveAttribute("aria-current", "page");
    expect(screen.getByText(MANUAL_MARKER)).toBeInTheDocument();
  });

  it("lands on the Manual tab from the extraction failure manual-entry link", async () => {
    const user = userEvent.setup();
    renderAt("/imports/schedule-e/extract");

    await user.upload(
      screen.getByLabelText(/choose your schedule e pages/i),
      new File(["%PDF-1.4"], "return.pdf", { type: "application/pdf" }),
    );
    await user.click(
      await screen.findByRole("link", { name: /enter your schedule e manually/i }),
    );

    expect(screen.getByTestId("pathname").textContent).toBe(
      "/imports/schedule-e",
    );
    expect(tab(/enter manually/i)).toHaveAttribute("aria-current", "page");
    expect(tab(/upload pdf/i)).not.toHaveAttribute("aria-current");
    expect(screen.getByText(MANUAL_MARKER)).toBeInTheDocument();
  });

  it("shows NotFound for an unknown /imports child route", () => {
    renderAt("/imports/foo");

    expect(
      screen.getByRole("heading", { name: /page not found/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: /import methods/i }),
    ).not.toBeInTheDocument();
  });
});
