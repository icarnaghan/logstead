import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import YearEndChecklistPage from "./YearEndChecklistPage";
import type {
  ChecklistItem,
  ChecklistStatus,
  YearEndChecklist,
} from "../api/yearEndChecklist";
import { latestCompletedTaxYear } from "../lib/taxYears";
import { ThemeProvider } from "../theme/ThemeProvider";

vi.mock("../api/properties", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/properties")>()),
  getEarliestDataYear: vi.fn().mockResolvedValue(null),
}));

const LATEST = latestCompletedTaxYear();

function item(
  id: string,
  status: ChecklistStatus,
  link = "/properties/prop-1/transactions",
): ChecklistItem {
  return { id, title: `Title ${id}`, status, reason: `Reason ${id}`, link };
}

function checklist(
  items: ChecklistItem[],
  taxYear = LATEST,
): YearEndChecklist {
  const count = (s: ChecklistStatus) =>
    items.filter((i) => i.status === s).length;
  return {
    property_id: "prop-1",
    tax_year: taxYear,
    thresholds: {},
    counts: {
      done: count("done"),
      needs_attention: count("needs_attention"),
      not_applicable: count("not_applicable"),
      total: items.length,
    },
    items,
  };
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="search">{location.search}</div>;
}

function renderPage(getChecklist: ReturnType<typeof vi.fn>, search = "") {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[`/properties/prop-1/checklist${search}`]}>
        <Routes>
          <Route
            path="/properties/:propertyId/checklist"
            element={<YearEndChecklistPage api={{ getChecklist }} />}
          />
        </Routes>
        <LocationProbe />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

const disclaimer = () => screen.getByRole("note");

describe("YearEndChecklistPage", () => {
  it("shows a loading region and the disclaimer while loading", () => {
    renderPage(vi.fn(() => new Promise(() => {})));
    expect(screen.getByLabelText("Loading checklist")).toBeInTheDocument();
    expect(disclaimer()).toHaveTextContent(/not tax advice/i);
    expect(
      screen.getAllByRole("heading", { level: 1 }),
    ).toHaveLength(1);
    expect(
      screen.getByRole("heading", { level: 1, name: "Year-end checklist" }),
    ).toBeInTheDocument();
  });

  it("shows an error with retry, keeps the disclaimer, and retries", async () => {
    const user = userEvent.setup();
    const getChecklist = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValue(checklist([item("income_entered", "done")]));
    renderPage(getChecklist);
    await user.click(await screen.findByRole("button", { name: /retry/i }));
    expect(await screen.findByText("Title income_entered")).toBeInTheDocument();
    expect(getChecklist).toHaveBeenCalledTimes(2);
    expect(disclaimer()).toBeInTheDocument();
  });

  it("shows the error state with the disclaimer", async () => {
    renderPage(vi.fn().mockRejectedValue(new Error("boom")));
    expect(
      await screen.findByText("Could not load the checklist"),
    ).toBeInTheDocument();
    expect(disclaimer()).toBeInTheDocument();
  });

  it("renders an all-clear year with the counts text in a polite live region", async () => {
    renderPage(
      vi.fn().mockResolvedValue(
        checklist([item("a", "done"), item("b", "not_applicable")]),
      ),
    );
    await screen.findByText("Title a");
    const status = screen
      .getAllByRole("status")
      .find((el) => el.getAttribute("aria-live") === "polite")!;
    expect(status).toHaveTextContent("0 need attention, 1 done, 1 not applicable");
    expect(disclaimer()).toBeInTheDocument();
  });

  it("lists needs-attention items first with a list role and accessible link names", async () => {
    renderPage(
      vi.fn().mockResolvedValue(
        checklist([
          item("a", "done"),
          item("b", "needs_attention", "/properties/prop-1/loans"),
          item("c", "not_applicable"),
          item("d", "needs_attention", "/carryforward"),
        ]),
      ),
    );
    await screen.findByText("Title a");
    const list = screen
      .getAllByRole("list")
      .find((l) => within(l).queryByText("Title a"))!;
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((r) => within(r).getByRole("heading").textContent)).toEqual([
      "Title b",
      "Title d",
      "Title a",
      "Title c",
    ]);
    expect(
      screen.getByRole("link", { name: "Loans: Title b" }),
    ).toHaveAttribute("href", "/properties/prop-1/loans");
    expect(
      screen.getByRole("link", { name: "Carryforward: Title d" }),
    ).toHaveAttribute("href", "/carryforward");
    expect(
      screen.getByRole("link", { name: "Transactions: Title a" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Needs attention").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Done").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Not applicable").length).toBeGreaterThan(0);
  });

  it("shows an empty state for a year without items and keeps the disclaimer", async () => {
    renderPage(vi.fn().mockResolvedValue(checklist([])));
    expect(await screen.findByText("Nothing to check")).toBeInTheDocument();
    expect(screen.queryByText(/^Title /)).toBeNull();
    expect(disclaimer()).toBeInTheDocument();
  });

  it("has no control that changes data", async () => {
    renderPage(
      vi.fn().mockResolvedValue(checklist([item("a", "needs_attention")])),
    );
    await screen.findByText("Title a");
    expect(
      screen.queryByRole("button", {
        name: /save|delete|add|import|edit|submit|create|remove/i,
      }),
    ).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("defaults to the latest completed tax year", async () => {
    const getChecklist = vi.fn().mockResolvedValue(checklist([]));
    renderPage(getChecklist);
    await screen.findByText("Nothing to check");
    expect(getChecklist).toHaveBeenCalledWith(
      "prop-1",
      LATEST,
      expect.anything(),
    );
    expect(screen.getByLabelText("Tax year")).toHaveValue(String(LATEST));
  });

  it("uses the year parameter and writes a changed year back to the URL", async () => {
    const user = userEvent.setup();
    const getChecklist = vi.fn().mockResolvedValue(checklist([]));
    renderPage(getChecklist, `?year=${LATEST - 1}`);
    await screen.findByText("Nothing to check");
    expect(getChecklist).toHaveBeenCalledWith(
      "prop-1",
      LATEST - 1,
      expect.anything(),
    );
    await user.selectOptions(screen.getByLabelText("Tax year"), String(LATEST));
    expect(screen.getByTestId("search")).toHaveTextContent(`year=${LATEST}`);
    await vi.waitFor(() =>
      expect(getChecklist).toHaveBeenCalledWith(
        "prop-1",
        LATEST,
        expect.anything(),
      ),
    );
  });

  it("keeps previous content while a year change reloads", async () => {
    const user = userEvent.setup();
    let release: (value: YearEndChecklist) => void = () => {};
    const getChecklist = vi
      .fn()
      .mockResolvedValueOnce(checklist([item("a", "done")]))
      .mockImplementationOnce(
        () => new Promise<YearEndChecklist>((r) => (release = r)),
      );
    renderPage(getChecklist);
    await screen.findByText("Title a");
    await user.selectOptions(screen.getByLabelText("Tax year"), String(LATEST - 1));
    expect(screen.getByText("Title a")).toBeInTheDocument();
    release(checklist([item("z", "done")], LATEST - 1));
    expect(await screen.findByText("Title z")).toBeInTheDocument();
  });
});
