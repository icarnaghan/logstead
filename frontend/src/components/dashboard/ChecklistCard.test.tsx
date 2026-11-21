import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DashboardSummary, TrendsSeries } from "../../api/dashboard";
import { ChecklistCard } from "./ChecklistCard";
import { SetupGuideProvider } from "../../lib/setupGuide";
import {
  checklistKeys,
  readFlag,
  useMarkReportVisited,
} from "../../lib/checklistStorage";

const { listLoans, listAssets, getUserProfile } = vi.hoisted(() => ({
  listLoans: vi.fn(),
  listAssets: vi.fn(),
  getUserProfile: vi.fn(),
}));

vi.mock("../../api/loans", () => ({ listLoans }));
vi.mock("../../api/assets", () => ({ listAssets }));
vi.mock("../../lib/auth", () => ({ getUserProfile }));

/**
 * ChecklistCard tests (task 34.7, Requirements 24.1-24.10, design D14).
 */

const SUMMARY: DashboardSummary = {
  tax_year: 2024,
  has_properties: true,
  total_income: "0.00",
  total_expenses: "0.00",
  net: "0.00",
  properties: [],
  empty_state_prompt: null,
};

function year(over: { income?: string; expenses?: string; dep?: string } = {}) {
  return {
    tax_year: 2024,
    total_income: over.income ?? "0.00",
    total_expenses: over.expenses ?? "0.00",
    net: "0.00",
    depreciation_total: over.dep ?? "0.00",
    properties: [
      {
        property_id: "p1",
        property_name: "Maple",
        total_income: "0.00",
        total_expenses: "0.00",
        net: "0.00",
      },
      {
        property_id: "p2",
        property_name: "Oak",
        total_income: "0.00",
        total_expenses: "0.00",
        net: "0.00",
      },
    ],
  };
}

const EMPTY_TRENDS: TrendsSeries = { years: [year()] };
const TXN_TRENDS: TrendsSeries = { years: [year({ income: "100.00" })] };
const DEP_TRENDS: TrendsSeries = { years: [year({ dep: "50.00" })] };

function renderCard(
  props: Partial<React.ComponentProps<typeof ChecklistCard>> = {},
) {
  return render(
    <MemoryRouter>
      <ChecklistCard
        summary={SUMMARY}
        trends={EMPTY_TRENDS}
        loading={false}
        error={false}
        {...props}
      />
    </MemoryRouter>,
  );
}

/** Replaces the default in-memory localStorage (setup.ts) with one that throws. */
function installMemoryLocalStorage(failing = false) {
  const data = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    value: {
      getItem: (k: string) => {
        if (failing) throw new Error("denied");
        return data.get(k) ?? null;
      },
      setItem: (k: string, v: string) => {
        if (failing) throw new Error("denied");
        data.set(k, String(v));
      },
      removeItem: (k: string) => void data.delete(k),
      clear: () => data.clear(),
    },
    configurable: true,
  });
}

beforeEach(() => {
  listLoans.mockReset().mockResolvedValue([]);
  listAssets.mockReset().mockResolvedValue([]);
  getUserProfile.mockReset().mockReturnValue({ sub: "user-1" });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function VisitHarness() {
  useMarkReportVisited();
  return null;
}

describe("useMarkReportVisited (report pages)", () => {
  it("sets the visited flag for the current user on mount", () => {
    expect(readFlag(checklistKeys("user-1").visited)).toBe(false);
    render(<VisitHarness />);
    expect(readFlag(checklistKeys("user-1").visited)).toBe(true);
    expect(readFlag(checklistKeys("user-2").visited)).toBe(false);
  });
});

describe("ChecklistCard — steps and progress", () => {
  it("renders the four steps in order with progress text and link targets", async () => {
    renderCard({ summary: { ...SUMMARY, has_properties: false } });
    expect(
      await screen.findByRole("heading", { name: "Get set up" }),
    ).toBeInTheDocument();
    expect(screen.getByText("0 of 4 done")).toBeInTheDocument();

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(4);
    const links = screen
      .getAllByRole("link")
      .filter((l) => l.textContent !== "Explore with sample data");
    expect(links.map((l) => l.textContent)).toEqual([
      "Add your first property",
      "Record a transaction",
      "Add a loan or a depreciable asset",
      "View a Schedule E report",
    ]);
    // First property id comes from the trends series.
    expect(links.map((l) => l.getAttribute("href"))).toEqual([
      "/properties",
      "/properties/p1/transactions",
      "/properties/p1/assets",
      "/reports",
    ]);
  });

  it("falls back to /properties when there is no property", () => {
    renderCard({
      summary: { ...SUMMARY, has_properties: false },
      trends: { years: [] },
    });
    const hrefs = screen
      .getAllByRole("link")
      .filter((l) => l.textContent !== "Explore with sample data")
      .map((l) => l.getAttribute("href"));
    expect(hrefs).toEqual([
      "/properties",
      "/properties",
      "/properties",
      "/reports",
    ]);
  });

  it("shows completed steps as non-links with 'Completed' text and counts progress", async () => {
    renderCard({ trends: TXN_TRENDS });
    expect(await screen.findByText("2 of 4 done")).toBeInTheDocument();
    expect(screen.getAllByText("Completed")).toHaveLength(2);
    expect(
      screen.queryByRole("link", { name: "Add your first property" }),
    ).toBeNull();
    expect(
      screen.queryByRole("link", { name: "Record a transaction" }),
    ).toBeNull();
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });

  it("has no axe violations", async () => {
    const { container } = renderCard({ trends: TXN_TRENDS });
    await screen.findByText("2 of 4 done");
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("ChecklistCard — visibility", () => {
  it("shows 'You're set up' with Dismiss when all four steps are complete", async () => {
    window.localStorage.setItem(checklistKeys("user-1").visited, "1");
    const all: TrendsSeries = {
      years: [year({ income: "100.00", dep: "50.00" })],
    };
    renderCard({ trends: all });
    expect(screen.getByText("You're set up")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Get set up" })).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("You're set up")).toBeNull();
    expect(window.localStorage.getItem(checklistKeys("user-1").dismissed)).toBe("1");
  });

  it("shows a skeleton and no heading while loading", () => {
    const { container } = renderCard({ loading: true, trends: null });
    expect(screen.queryByRole("heading", { name: "Get set up" })).toBeNull();
    expect(container).not.toBeEmptyDOMElement();
  });

  it("renders nothing on error", () => {
    const { container } = renderCard({ error: true, trends: null });
    expect(container).toBeEmptyDOMElement();
  });

  it("makes no backend call for the dismissed or visited flags", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    renderCard({ trends: DEP_TRENDS });
    await userEvent.click(
      await screen.findByRole("button", { name: "Dismiss setup checklist" }),
    );
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(listLoans).not.toHaveBeenCalled();
  });
});

describe("ChecklistCard — dismissal persistence", () => {
  it("persists dismissal per user and hides the card", async () => {
    const { container, unmount } = renderCard();
    await userEvent.click(
      screen.getByRole("button", { name: "Dismiss setup checklist" }),
    );
    expect(container).toBeEmptyDOMElement();
    expect(window.localStorage.getItem(checklistKeys("user-1").dismissed)).toBe(
      "1",
    );
    // Not stored under the anonymous key or another user's key.
    expect(window.localStorage.getItem(checklistKeys(null).dismissed)).toBeNull();
    unmount();

    // Same user: still hidden after remount.
    const again = renderCard();
    expect(again.container).toBeEmptyDOMElement();
    again.unmount();

    // Different user: card is visible again.
    getUserProfile.mockReturnValue({ sub: "user-2" });
    renderCard();
    expect(
      screen.getByRole("heading", { name: "Get set up" }),
    ).toBeInTheDocument();
  });

  it("reads the visited flag keyed by user id", () => {
    window.localStorage.setItem(checklistKeys("user-1").visited, "1");
    renderCard();
    expect(screen.getByText("2 of 4 done")).toBeInTheDocument();

    document.body.innerHTML = "";
    getUserProfile.mockReturnValue({ sub: "user-2" });
    renderCard();
    expect(screen.getByText("1 of 4 done")).toBeInTheDocument();
  });

  it("treats storage failure as unset without errors", async () => {
    installMemoryLocalStorage(true);
    renderCard();
    expect(screen.getByText("1 of 4 done")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Dismiss setup checklist" }),
    );
    // Dismissal still hides for this session.
    expect(screen.queryByRole("heading", { name: "Get set up" })).toBeNull();
  });
});

describe("ChecklistCard — loan/asset probe (D14)", () => {
  it("skips the probe when trends show non-zero depreciation", async () => {
    renderCard({ trends: DEP_TRENDS });
    expect(await screen.findByText("2 of 4 done")).toBeInTheDocument();
    expect(listLoans).not.toHaveBeenCalled();
    expect(listAssets).not.toHaveBeenCalled();
  });

  it("marks the step done when a probed property has a loan", async () => {
    listLoans.mockImplementation((id: string) =>
      Promise.resolve(id === "p2" ? [{ id: "l1" }] : []),
    );
    renderCard();
    expect(await screen.findByText("2 of 4 done")).toBeInTheDocument();
    expect(listLoans).toHaveBeenCalledWith("p1");
    expect(listAssets).toHaveBeenCalledWith("p2");
  });

  it("marks the step done when a probed property has an asset", async () => {
    listAssets.mockResolvedValue([{ id: "a1" }]);
    renderCard();
    expect(await screen.findByText("2 of 4 done")).toBeInTheDocument();
  });

  it("treats a probe failure as not done without surfacing an error", async () => {
    listLoans.mockRejectedValue(new Error("boom"));
    renderCard();
    await waitFor(() => expect(listLoans).toHaveBeenCalled());
    expect(screen.getByText("1 of 4 done")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("probes at most the first 5 properties", async () => {
    const many = year();
    many.properties = Array.from({ length: 8 }, (_, i) => ({
      property_id: `q${i}`,
      property_name: `P${i}`,
      total_income: "0.00",
      total_expenses: "0.00",
      net: "0.00",
    }));
    renderCard({ trends: { years: [many] } });
    await waitFor(() => expect(listLoans).toHaveBeenCalledTimes(5));
    expect(listAssets).toHaveBeenCalledTimes(5);
  });

  it("does not probe once dismissed", async () => {
    window.localStorage.setItem(checklistKeys("user-1").dismissed, "1");
    renderCard();
    await Promise.resolve();
    expect(listLoans).not.toHaveBeenCalled();
  });
});

describe("ChecklistCard — setup guide", () => {
  it("marks the first incomplete step as Next with a reason", () => {
    renderCard({ trends: TXN_TRENDS });
    expect(screen.getByText("Next")).toBeInTheDocument();
    expect(screen.getAllByText(/Loan interest and depreciation/)).toHaveLength(1);
  });

  it("collapses and expands, persisting per user", async () => {
    const { unmount } = renderCard();
    const btn = screen.getByRole("button", { name: "Collapse" });
    expect(btn).toHaveAttribute("aria-expanded", "true");
    expect(btn).toHaveAttribute("aria-controls", "checklist-steps");
    await userEvent.click(btn);
    const expand = screen.getByRole("button", { name: "Expand" });
    expect(expand).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById("checklist-steps")).toHaveAttribute("hidden");
    expect(screen.getByText("1 of 4 done")).toBeInTheDocument();
    unmount();
    renderCard();
    expect(screen.getByRole("button", { name: "Expand" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(screen.getByRole("button", { name: "Collapse" })).toBeInTheDocument();
  });

  it("shows the sample data link only while the user owns no property", () => {
    const first = renderCard({ summary: { ...SUMMARY, has_properties: false } });
    const link = screen.getByRole("link", { name: "Explore with sample data" });
    expect(link).toHaveAttribute("href", "/profile?focus=backup");
    expect(screen.getByText(/replaces all current data/)).toBeInTheDocument();
    first.unmount();
    renderCard();
    expect(screen.queryByRole("link", { name: "Explore with sample data" })).toBeNull();
  });

  it("announces a newly completed step in a status region", async () => {
    const view = renderCard({ trends: EMPTY_TRENDS });
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("");
    view.rerender(
      <MemoryRouter>
        <ChecklistCard summary={SUMMARY} trends={TXN_TRENDS} loading={false} error={false} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Record a transaction done. 2 of 4 done.",
    );
  });

  it("re-reads the stored state when the reset signal changes", () => {
    window.localStorage.setItem(checklistKeys("user-1").dismissed, "1");
    const ui = (n: number) => (
      <MemoryRouter>
        <SetupGuideProvider showSetupGuide={() => {}} resetSignal={n}>
          <ChecklistCard summary={SUMMARY} trends={EMPTY_TRENDS} loading={false} error={false} />
        </SetupGuideProvider>
      </MemoryRouter>
    );
    const view = render(ui(0));
    expect(view.container).toBeEmptyDOMElement();
    window.localStorage.removeItem(checklistKeys("user-1").dismissed);
    view.rerender(ui(1));
    expect(screen.getByRole("heading", { name: "Get set up" })).toBeInTheDocument();
  });
});
