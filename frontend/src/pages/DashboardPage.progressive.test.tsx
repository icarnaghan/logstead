import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DashboardPage from "./DashboardPage";
import type {
  DashboardApi,
  DashboardSummary,
  TrendsSeries,
} from "../api/dashboard";
import { ThemeProvider } from "../theme/ThemeProvider";

const { listLoans, listAssets, getUserProfile } = vi.hoisted(() => ({
  listLoans: vi.fn(),
  listAssets: vi.fn(),
  getUserProfile: vi.fn(),
}));

vi.mock("../api/loans", () => ({ listLoans }));
vi.mock("../api/assets", () => ({ listAssets }));
vi.mock("../lib/auth", () => ({ getUserProfile }));

// The Year-end checklist card loads on its own; an empty portfolio omits it so
// these tests stay about the existing dashboard content.
vi.mock("../api/yearEndChecklist", () => ({
  yearEndChecklistApi: {
    getPortfolioSummary: () => Promise.resolve({ tax_year: 2024, properties: [] }),
  },
}));

/**
 * Progressive rendering for the Dashboard (task 34.7, Requirements 23.1-23.6,
 * 24.1-24.6). Each data source is a deferred promise the test resolves or
 * rejects on demand. The chart error boundary is covered by
 * `DashboardPage.errorBoundary.test.tsx`.
 */

const YEAR = new Date().getFullYear();

const SUMMARY: DashboardSummary = {
  tax_year: YEAR,
  has_properties: true,
  total_income: "1500.00",
  total_expenses: "250.00",
  net: "1250.00",
  properties: [],
  empty_state_prompt: null,
};

const TRENDS: TrendsSeries = {
  years: [
    {
      tax_year: YEAR,
      total_income: "1500.00",
      total_expenses: "250.00",
      net: "1250.00",
      depreciation_total: "100.00",
      properties: [
        {
          property_id: "p1",
          property_name: "Maple Duplex",
          total_income: "1500.00",
          total_expenses: "250.00",
          net: "1250.00",
        },
      ],
    },
  ],
};

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function makeApi(overrides: Partial<DashboardApi> = {}): DashboardApi {
  return {
    getDashboard: vi.fn().mockResolvedValue(SUMMARY),
    getPropertySummaries: vi.fn().mockResolvedValue([]),
    getTrends: vi.fn().mockResolvedValue(TRENDS),
    ...overrides,
  } as unknown as DashboardApi;
}

function tree(api: DashboardApi) {
  return (
    <ThemeProvider>
      <MemoryRouter initialEntries={["/"]}>
        <DashboardPage api={api} />
      </MemoryRouter>
    </ThemeProvider>
  );
}

const headline = () =>
  screen.queryByRole("region", { name: /portfolio net for/i });
const checklist = () => screen.queryByRole("heading", { name: "Get set up" });

beforeEach(() => {
  listLoans.mockReset().mockResolvedValue([]);
  listAssets.mockReset().mockResolvedValue([]);
  getUserProfile.mockReset().mockReturnValue({ sub: "user-1" });
});

describe("Dashboard — progressive rendering (Req 23.1-23.2)", () => {
  it("renders header and Quick actions at once, then each source replaces its skeleton", async () => {
    const summary = deferred<DashboardSummary>();
    const trends = deferred<TrendsSeries>();
    const api = makeApi({
      getDashboard: vi.fn().mockReturnValue(summary.promise),
      getTrends: vi.fn().mockReturnValue(trends.promise),
    });
    render(tree(api));

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Quick actions" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Loading dashboard" })).toBeInTheDocument();
    expect(headline()).toBeNull();

    // Trends arrive first: the trends region fills in; the checklist waits on summary.
    await act(async () => trends.resolve(TRENDS));
    expect(await screen.findByRole("region", { name: /portfolio net for/i })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading dashboard" })).toBeNull();
    expect(checklist()).toBeNull();

    // Summary arrives later: the checklist appears without disturbing the trends.
    await act(async () => summary.resolve(SUMMARY));
    expect(await screen.findByRole("heading", { name: "Get set up" })).toBeInTheDocument();
    expect(headline()).toBeInTheDocument();
  });

  it("keeps Quick actions and header mounted when a source fails", async () => {
    const api = makeApi({
      getTrends: vi.fn().mockRejectedValue(new Error("boom")),
    });
    render(tree(api));
    expect(await screen.findByText("Your portfolio trends did not load.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Quick actions" })).toBeInTheDocument();
  });
});

describe("Dashboard — per-source errors and Retry (Req 23.3-23.4)", () => {
  it("shows one error with Retry for a failed trends request and retries only trends", async () => {
    const getTrends = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValue(TRENDS);
    const api = makeApi({ getTrends });
    render(tree(api));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Your portfolio trends did not load.")).toBeInTheDocument();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    // Checklist is hidden on a trends error; Quick actions unaffected.
    expect(checklist()).toBeNull();
    expect(screen.getByRole("heading", { name: "Quick actions" })).toBeInTheDocument();
    expect(api.getDashboard).toHaveBeenCalledTimes(1);

    await userEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("region", { name: /portfolio net for/i })).toBeInTheDocument();
    expect(getTrends).toHaveBeenCalledTimes(2);
    expect(api.getDashboard).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows one error with Retry for a failed summary and retries only the summary", async () => {
    const getDashboard = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValue(SUMMARY);
    const api = makeApi({ getDashboard });
    render(tree(api));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Your property summary did not load.")).toBeInTheDocument();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();

    await userEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(getDashboard).toHaveBeenCalledTimes(2);
    expect(api.getTrends).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("region", { name: /portfolio net for/i })).toBeInTheDocument();
  });
});

describe("Dashboard — refresh keeps content mounted (Req 23.5)", () => {
  it("keeps tiles mounted while refreshing and after a refresh failure", async () => {
    const { rerender } = render(tree(makeApi()));
    expect(await screen.findByRole("region", { name: /portfolio net for/i })).toBeInTheDocument();
    const before = headline();

    // A new api instance triggers a refresh of both sources; hold trends open.
    const trends = deferred<TrendsSeries>();
    rerender(
      tree(makeApi({ getTrends: vi.fn().mockReturnValue(trends.promise) })),
    );
    expect(headline()).toBe(before);
    expect(screen.queryByRole("status", { name: "Loading dashboard" })).toBeNull();

    // The refresh fails: content stays and a compact error with Retry appears.
    await act(async () => trends.reject(new Error("boom")));
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Your portfolio trends did not load.")).toBeInTheDocument();
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(headline()).toBe(before);
  });
});

describe("Dashboard — checklist visibility (Req 24.1-24.6)", () => {
  it("is hidden when the user has no properties (empty state only)", async () => {
    const api = makeApi({
      getDashboard: vi.fn().mockResolvedValue({
        ...SUMMARY,
        has_properties: false,
        empty_state_prompt: "Add your first property to get started.",
      }),
    });
    render(tree(api));
    expect(await screen.findByText("Add your first property to get started.")).toBeInTheDocument();
    expect(checklist()).toBeNull();
  });

  it("is hidden once dismissed", async () => {
    render(tree(makeApi()));
    await userEvent.click(
      await screen.findByRole("button", { name: "Dismiss setup checklist" }),
    );
    expect(checklist()).toBeNull();
    expect(headline()).toBeInTheDocument();
  });

  it("shows the set-up state when every step is complete", async () => {
    window.localStorage.setItem("logstead.checklist.visitedReport.user-1", "1");
    render(tree(makeApi()));
    expect(await screen.findByRole("region", { name: /portfolio net for/i })).toBeInTheDocument();
    expect(checklist()).toBeInTheDocument();
    expect(screen.getByText("You're set up")).toBeInTheDocument();
  });

  it("is visible with progress while steps remain", async () => {
    render(tree(makeApi()));
    expect(await screen.findByText("3 of 4 done")).toBeInTheDocument();
  });
});
