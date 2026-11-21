import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import LoansPage, { type LoansApi } from "./LoansPage";
import { ApiError } from "../lib/apiClient";
import { ToastProvider } from "../components/ui";
import { ThemeProvider } from "../theme/ThemeProvider";
import { todayIso } from "../components/loans/loanFormModel";
import {
  clearInterestOverride,
  setInterestOverride,
  type Loan,
  type YearlyRollup,
} from "../api/loans";

// InterestOverrideControl calls the loans module directly, not the injected
// api, so stub the module's network functions to keep tests offline.
vi.mock("../api/loans", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/loans")>();
  return {
    ...actual,
    setInterestOverride: vi.fn(),
    clearInterestOverride: vi.fn(),
  };
});


/**
 * Page tests for the per-property Loans page (task 16.10,
 * Requirements 9.4, 9.5, 9.15, 9.17, 9.18, 9.20).
 */

function loan(overrides: Partial<Loan> = {}): Loan {
  return {
    id: "loan-1",
    property_id: "prop-1",
    description: "Main mortgage",
    annual_interest_rate: "6.000",
    monthly_payment: "1498.88",
    anchor_balance: "200000.00",
    anchor_date: "2023-06-15",
    extra_principal: "0.00",
    original_principal: null,
    closing_date: null,
    payoff_date: null,
    include_in_report: true,
    interest_overrides: {},
    remaining_payments: 200,
    next_payment_date: "2023-07-15",
    projected_payoff_date: "2040-02-15",
    payoff_balance: null,
    status: "active",
    created_at: "2023-01-01T00:00:00Z",
    updated_at: "2023-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeApi(overrides: Partial<LoansApi> = {}): LoansApi {
  return {
    listLoans: vi.fn().mockResolvedValue([]),
    createLoan: vi.fn().mockResolvedValue(loan()),
    updateLoan: vi.fn().mockResolvedValue(loan()),
    deleteLoan: vi.fn().mockResolvedValue(undefined),
    getLoanSchedule: vi.fn().mockResolvedValue({
      loan_id: "loan-1",
      estimate: true,
      payoff_balance: null,
      payments: [],
      yearly: [],
    }),
    setInterestOverride: vi.fn(),
    clearInterestOverride: vi.fn(),
    getLine12Impact: vi.fn().mockResolvedValue([]),
    ...overrides,
  };
}

function renderPage(api: LoansApi, search = "") {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={[`/properties/prop-1/loans${search}`]}>
          <Routes>
            <Route
              path="/properties/:propertyId/loans"
              element={<LoansPage api={api} />}
            />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

async function fillValid(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Description"), "New loan");
  await user.type(screen.getByLabelText("Annual interest rate (%)"), "6");
  await user.type(
    screen.getByLabelText("Monthly payment (principal and interest)"),
    "1500",
  );
  await user.type(screen.getByLabelText("Anchor balance"), "250000");
  fireEvent.change(screen.getByLabelText("Anchor date"), {
    target: { value: "2024-01-01" },
  });
}

/** The open modal dialog. */
function modalDialog(): HTMLElement {
  return screen.getByRole("dialog");
}

/** The modal form's submit button (type="submit"). */
function submitButton(): HTMLElement {
  const btn = within(modalDialog())
    .getAllByRole("button")
    .find((b) => b.getAttribute("type") === "submit");
  if (!btn) throw new Error("submit button not found");
  return btn;
}

/** Radix registers its outside-interaction listeners on a timer. */
const tick = () => new Promise((r) => setTimeout(r, 10));

/** The "Add loan" button beside the list heading (not the empty-state one). */
function addButton(): HTMLElement {
  return screen.getByRole("button", { name: "Add loan" });
}

async function openAddFromEmpty(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText("No loans yet");
  await user.click(screen.getByRole("button", { name: "Add loan" }));
  await screen.findByRole("dialog");
}

describe("LoansPage — estimate notice (Req 9.15)", () => {
  it("shows the estimate notice", async () => {
    renderPage(makeApi());
    await screen.findByText("No loans yet");
    expect(screen.getByRole("note")).toHaveTextContent(/estimate/i);
  });
});

describe("LoansPage — list and Add control (Req 1.1, 1.3, 1.4, 1.5, 1.7)", () => {
  it("shows the empty state with an Add loan action and no form", async () => {
    renderPage(makeApi());
    expect(await screen.findByText("No loans yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add loan" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Description")).not.toBeInTheDocument();
  });

  it("shows the table and an Add loan button, with no form while closed", async () => {
    renderPage(makeApi({ listLoans: vi.fn().mockResolvedValue([loan()]) }));
    await screen.findAllByText("Main mortgage");
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(addButton()).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Anchor balance")).not.toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("hides Add while loading", async () => {
    renderPage(
      makeApi({ listLoans: vi.fn().mockReturnValue(new Promise(() => {})) }),
    );
    await screen.findByRole("status", { name: "Loading loans" });
    expect(
      screen.queryByRole("button", { name: "Add loan" }),
    ).not.toBeInTheDocument();
  });

  it("hides Add when the list fails to load", async () => {
    renderPage(
      makeApi({
        listLoans: vi.fn().mockRejectedValue(new ApiError(500, "boom", null)),
      }),
    );
    expect(await screen.findByText(/Unable to load loans/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add loan" }),
    ).not.toBeInTheDocument();
  });
});

describe("LoansPage — Add and Edit modals (Req 2.1, 2.2, 3.1, 3.2, 6.3)", () => {
  it("opens an empty Add modal with today's anchor date", async () => {
    const user = userEvent.setup();
    renderPage(makeApi({ listLoans: vi.fn().mockResolvedValue([loan()]) }));
    await screen.findAllByText("Main mortgage");
    await user.click(addButton());

    const dialog = await screen.findByRole("dialog", { name: "Add loan" });
    expect(within(dialog).getByLabelText("Description")).toHaveValue("");
    expect(within(dialog).getByLabelText("Anchor balance")).toHaveValue("");
    expect(within(dialog).getByLabelText("Anchor date")).toHaveValue(
      todayIso(),
    );
  });

  it("opens a prefilled Edit modal", async () => {
    const user = userEvent.setup();
    renderPage(makeApi({ listLoans: vi.fn().mockResolvedValue([loan()]) }));
    await user.click(
      (await screen.findAllByRole("button", { name: "Edit Main mortgage" }))[0],
    );

    const dialog = await screen.findByRole("dialog", { name: "Edit loan" });
    expect(within(dialog).getByLabelText("Description")).toHaveValue(
      "Main mortgage",
    );
    expect(within(dialog).getByLabelText("Anchor balance")).toHaveValue(
      "200,000.00",
    );
    expect(within(dialog).getByLabelText("Anchor date")).toHaveValue(
      "2023-06-15",
    );
    expect(
      within(dialog).getByRole("button", { name: "Save changes" }),
    ).toBeInTheDocument();
  });

  it("shows the preview and anchor help inside the modal", async () => {
    const user = userEvent.setup();
    renderPage(makeApi({ listLoans: vi.fn().mockResolvedValue([loan()]) }));
    await user.click(
      (await screen.findAllByRole("button", { name: "Edit Main mortgage" }))[0],
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByTestId("loan-preview")).toBeInTheDocument();
    expect(
      within(dialog).getByText(/anchor balance is the balance after/i),
    ).toBeInTheDocument();
  });

  it("keeps notices and the schedule outside the modal", async () => {
    const user = userEvent.setup();
    renderPage(
      makeApi({
        listLoans: vi.fn().mockResolvedValue([loan()]),
        getLoanSchedule: vi.fn().mockResolvedValue(schedule([yearly(2023)])),
      }),
    );
    await user.click(
      (await screen.findAllByRole("button", { name: "Select Main mortgage" }))[0],
    );
    await screen.findByText(/Anchor year: 2023\./);
    await user.click(addButton());
    const dialog = await screen.findByRole("dialog");

    const notes = screen.getAllByRole("note", { hidden: true });
    expect(notes.length).toBeGreaterThan(0);
    for (const note of notes) expect(dialog).not.toContainElement(note);
    const heading = screen.getByRole("heading", {
      name: /Yearly schedule/,
      hidden: true,
    });
    expect(dialog).not.toContainElement(heading);
  });
});

describe("LoansPage — save success (Req 2.3, 2.4, 3.3, 3.4, 4.4)", () => {
  it("creates a loan, closes the modal, lists it and toasts", async () => {
    const user = userEvent.setup();
    const created = loan({ id: "loan-2", description: "New loan" });
    const api = makeApi({
      listLoans: vi.fn().mockResolvedValue([loan()]),
      createLoan: vi.fn().mockResolvedValue(created),
    });
    renderPage(api);
    await screen.findAllByText("Main mortgage");
    await user.click(addButton());
    await screen.findByRole("dialog");

    await fillValid(user);
    await user.click(submitButton());

    expect(api.createLoan).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Loan added")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect((await screen.findAllByText("New loan")).length).toBeGreaterThan(0);
    expect(api.getLine12Impact).toHaveBeenCalledTimes(2);
  });

  it("updates a loan, closes the modal, refreshes schedule and impact, and toasts", async () => {
    const user = userEvent.setup();
    const updated = loan({ description: "Renamed mortgage" });
    const api = makeApi({
      listLoans: vi.fn().mockResolvedValue([loan()]),
      updateLoan: vi.fn().mockResolvedValue(updated),
      getLoanSchedule: vi.fn().mockResolvedValue(schedule([yearly(2023)])),
    });
    renderPage(api);
    await user.click(
      (await screen.findAllByRole("button", { name: "Select Main mortgage" }))[0],
    );
    await screen.findByText(/Anchor year: 2023\./);
    expect(api.getLoanSchedule).toHaveBeenCalledTimes(1);
    expect(api.getLine12Impact).toHaveBeenCalledTimes(1);

    await user.click(
      screen.getAllByRole("button", { name: "Edit Main mortgage" })[0],
    );
    await screen.findByRole("dialog", { name: "Edit loan" });
    await user.click(submitButton());

    expect(api.updateLoan).toHaveBeenCalledWith(
      "prop-1",
      "loan-1",
      expect.objectContaining({ description: "Main mortgage" }),
    );
    expect(await screen.findByText("Loan updated")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(api.getLoanSchedule).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(api.getLine12Impact).toHaveBeenCalledTimes(2));
    expect(
      (await screen.findAllByText("Renamed mortgage")).length,
    ).toBeGreaterThan(0);
  });
});

describe("LoansPage — save errors (Req 5.1-5.4, 5.6)", () => {
  it("shows a field error, keeps the modal open and the entered values", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      createLoan: vi.fn().mockRejectedValue(
        new ApiError(400, "Invalid", {
          errors: [
            { field: "anchor_balance", message: "Balance is too large" },
          ],
        }),
      ),
    });
    renderPage(api);
    await openAddFromEmpty(user);

    await fillValid(user);
    await user.click(submitButton());

    expect((await screen.findAllByText("Balance is too large"))[0]).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Anchor balance")).toHaveValue("250000.00");
    expect(screen.getByLabelText("Description")).toHaveValue("New loan");
    expect(
      screen.getByLabelText("Monthly payment (principal and interest)"),
    ).toHaveValue("1,500.00");
    expect(screen.queryByText("Loan added")).not.toBeInTheDocument();
  });

  it("shows a form-level error in the modal and toasts when no field is named", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      createLoan: vi.fn().mockRejectedValue(new ApiError(500, "Server blew up", null)),
    });
    renderPage(api);
    await openAddFromEmpty(user);

    await fillValid(user);
    await user.click(submitButton());

    const alert = await within(screen.getByRole("dialog")).findByRole("alert");
    expect(alert).toHaveTextContent("Server blew up");
    expect(await screen.findByText("Could not save the loan")).toBeInTheDocument();
    expect(screen.getByLabelText("Description")).toHaveValue("New loan");
  });

  it("does not toast a field-level failure", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      createLoan: vi.fn().mockRejectedValue(
        new ApiError(400, "Invalid", {
          errors: [{ field: "anchor_balance", message: "Balance is too large" }],
        }),
      ),
    });
    renderPage(api);
    await openAddFromEmpty(user);
    await fillValid(user);
    await user.click(submitButton());
    expect((await screen.findAllByText("Balance is too large"))[0]).toBeInTheDocument();
    expect(screen.queryByText("Could not save the loan")).not.toBeInTheDocument();
  });

  it("clears errors after close and reopen", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      listLoans: vi.fn().mockResolvedValue([loan()]),
      createLoan: vi.fn().mockRejectedValue(
        new ApiError(400, "Invalid", {
          errors: [{ field: "anchor_balance", message: "Balance is too large" }],
        }),
      ),
    });
    renderPage(api);
    await screen.findAllByText("Main mortgage");
    await user.click(addButton());
    await screen.findByRole("dialog");
    await fillValid(user);
    await user.click(submitButton());
    expect((await screen.findAllByText("Balance is too large"))[0]).toBeInTheDocument();

    await user.click(within(modalDialog()).getByRole("button", { name: "Cancel" }));
    // The form is dirty, so closing asks to discard first.
    await user.click(await screen.findByRole("button", { name: "Discard" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    await user.click(addButton());
    await screen.findByRole("dialog");
    expect(screen.queryByText("Balance is too large")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Description")).toHaveValue("");
  });
});

describe("LoansPage — dismissal (Req 4.1-4.3, 4.5, 4.6)", () => {
  it("closes on Cancel without saving", async () => {
    const user = userEvent.setup();
    const api = makeApi({ listLoans: vi.fn().mockResolvedValue([loan()]) });
    renderPage(api);
    await screen.findAllByText("Main mortgage");
    await user.click(addButton());
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Cancel",
      }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(api.createLoan).not.toHaveBeenCalled();
    expect(api.updateLoan).not.toHaveBeenCalled();
  });

  it("closes on Escape without saving", async () => {
    const user = userEvent.setup();
    const api = makeApi({ listLoans: vi.fn().mockResolvedValue([loan()]) });
    renderPage(api);
    await screen.findAllByText("Main mortgage");
    await user.click(addButton());
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(api.createLoan).not.toHaveBeenCalled();
  });

  it("closes on backdrop click without saving", async () => {
    const user = userEvent.setup();
    const api = makeApi({ listLoans: vi.fn().mockResolvedValue([loan()]) });
    renderPage(api);
    await screen.findAllByText("Main mortgage");
    await user.click(addButton());
    await screen.findByRole("dialog");
    await tick();
    // Radix sets pointer-events: none on body, so dispatch the event directly.
    fireEvent.pointerDown(document.body);
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(api.createLoan).not.toHaveBeenCalled();
  });

  it("disables inputs and ignores Escape while a save is pending", async () => {
    const user = userEvent.setup();
    let resolve!: (l: Loan) => void;
    const api = makeApi({
      createLoan: vi.fn().mockReturnValue(
        new Promise<Loan>((r) => {
          resolve = r;
        }),
      ),
    });
    renderPage(api);
    await openAddFromEmpty(user);
    await fillValid(user);
    await user.click(submitButton());

    await waitFor(() => expect(screen.getByLabelText("Description")).toBeDisabled());
    expect(submitButton()).toBeDisabled();
    expect(within(modalDialog()).getByRole("button", { name: "Cancel" })).toBeDisabled();
    await user.keyboard("{Escape}");
    await tick();
    fireEvent.pointerDown(document.body);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    resolve(loan({ id: "loan-2", description: "New loan" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });
});

describe("LoansPage — focus return (Req 6.4, 6.5)", () => {
  it("returns focus to the Add button", async () => {
    const user = userEvent.setup();
    renderPage(makeApi({ listLoans: vi.fn().mockResolvedValue([loan()]) }));
    await screen.findAllByText("Main mortgage");
    const add = addButton();
    await user.click(add);
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(add).toHaveFocus());
  });

  it("returns focus to the Edit button", async () => {
    const user = userEvent.setup();
    renderPage(makeApi({ listLoans: vi.fn().mockResolvedValue([loan()]) }));
    const edit = (
      await screen.findAllByRole("button", { name: "Edit Main mortgage" })
    )[0];
    await user.click(edit);
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Cancel",
      }),
    );
    await waitFor(() => expect(edit).toHaveFocus());
  });

  it("falls back to the All loans heading when the empty-state trigger is gone", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      createLoan: vi.fn().mockResolvedValue(loan({ id: "loan-2", description: "New loan" })),
    });
    renderPage(api);
    await openAddFromEmpty(user);
    await fillValid(user);
    await user.click(submitButton());
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "All loans" })).toHaveFocus(),
    );
  });
});

function yearly(
  year: number,
  overrides: Partial<YearlyRollup> = {},
): YearlyRollup {
  return {
    tax_year: year,
    payments: 6,
    interest: "5000.00",
    estimated_interest: "5000.00",
    interest_override: null,
    variance: null,
    principal: "3000.00",
    total_paid: "8000.00",
    ending_balance: "197000.00",
    ...overrides,
  };
}

function overrideOnly(year: number, interest: string): YearlyRollup {
  return yearly(year, {
    payments: 0,
    interest,
    estimated_interest: "0.00",
    interest_override: interest,
    variance: interest,
    principal: "0.00",
    total_paid: "0.00",
    ending_balance: null,
  });
}

function schedule(rows: YearlyRollup[]) {
  return {
    loan_id: "loan-1",
    estimate: true,
    payoff_balance: null,
    payments: [],
    yearly: rows,
  };
}

describe("LoansPage — anchor notice and override-only rows (Req 11.4, 11.5, 11.7, 11.8)", () => {
  it("shows the anchor-year notice and add-override form for the selected loan", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      listLoans: vi.fn().mockResolvedValue([loan()]),
      getLoanSchedule: vi.fn().mockResolvedValue(schedule([yearly(2023)])),
    });
    renderPage(api);

    await user.click(
      (await screen.findAllByRole("button", { name: "Select Main mortgage" }))[0],
    );

    expect(await screen.findByText(/Anchor year: 2023\./)).toBeInTheDocument();
    expect(
      screen.getByRole("form", { name: "Add interest override for a past year" }),
    ).toBeInTheDocument();
  });

  it("adds an override-only row after saving and removes it after clearing", async () => {
    const user = userEvent.setup();
    const getLoanSchedule = vi
      .fn()
      .mockResolvedValueOnce(schedule([yearly(2023)]))
      .mockResolvedValueOnce(schedule([overrideOnly(2020, "7010.12"), yearly(2023)]))
      .mockResolvedValueOnce(schedule([yearly(2023)]));
    const api = makeApi({
      listLoans: vi.fn().mockResolvedValue([loan()]),
      getLoanSchedule,
    });
    vi.mocked(setInterestOverride).mockResolvedValue(overrideOnly(2020, "7010.12"));
    vi.mocked(clearInterestOverride).mockResolvedValue(null);
    renderPage(api);

    await user.click(
      (await screen.findAllByRole("button", { name: "Select Main mortgage" }))[0],
    );
    await screen.findByText(/Anchor year: 2023\./);
    expect(screen.queryByText("Override only")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Tax year"), "2020");
    await user.type(screen.getByLabelText("Form 1098 interest"), "7010.12");
    await user.click(screen.getByRole("button", { name: "Add override" }));

    expect(setInterestOverride).toHaveBeenCalledWith(
      "prop-1",
      "loan-1",
      2020,
      "7010.12",
    );
    expect(await screen.findAllByText("Override only")).not.toHaveLength(0);
    expect(getLoanSchedule).toHaveBeenCalledTimes(2);

    const row = screen.getAllByText("Override only")[0].closest("tr") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: /clear/i }));

    await waitFor(() =>
      expect(screen.queryByText("Override only")).not.toBeInTheDocument(),
    );
    expect(clearInterestOverride).toHaveBeenCalledWith("prop-1", "loan-1", 2020);
  });

  it("keeps the superseded-interest notice", async () => {
    const api = makeApi({
      getLine12Impact: vi.fn().mockResolvedValue([
        {
          tax_year: 2023,
          loan_interest: "5000.00",
          superseded_manual_interest: { amount: "4000.00", count: 1 },
        },
      ]),
    });
    renderPage(api);
    await screen.findByText("No loans yet");
    expect(await screen.findByText(/loan interest replaces/)).toBeInTheDocument();
  });
});

describe("LoansPage — delete (Req 9.17, 9.18, 13.1-13.8)", () => {
  it("deletes a loan without overrides immediately and offers Undo", async () => {
    const user = userEvent.setup();
    const listLoans = vi
      .fn()
      .mockResolvedValueOnce([loan()])
      .mockResolvedValue([]);
    const api = makeApi({ listLoans });
    renderPage(api);

    await user.click(
      (await screen.findAllByRole("button", { name: "Delete Main mortgage" }))[0],
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.deleteLoan).toHaveBeenCalledWith("prop-1", "loan-1");
    expect(await screen.findByText("Loan deleted")).toBeInTheDocument();
    expect(await screen.findByText("No loans yet")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "All loans" })).toHaveFocus(),
    );

    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(api.createLoan).toHaveBeenCalledWith("prop-1", {
        description: "Main mortgage",
        annual_interest_rate: "6.000",
        monthly_payment: "1498.88",
        anchor_balance: "200000.00",
        anchor_date: "2023-06-15",
        extra_principal: "0.00",
        payoff_date: null,
        original_principal: null,
        closing_date: null,
        include_in_report: true,
      }),
    );
    expect(await screen.findByText("Loan restored")).toBeInTheDocument();
  });

  it("keeps the confirmation dialog and no Undo for a loan with overrides", async () => {
    const user = userEvent.setup();
    const listLoans = vi
      .fn()
      .mockResolvedValueOnce([loan({ interest_overrides: { "2024": "100.00" } })])
      .mockResolvedValue([]);
    const api = makeApi({ listLoans });
    renderPage(api);

    await user.click(
      (await screen.findAllByRole("button", { name: "Delete Main mortgage" }))[0],
    );
    expect(api.deleteLoan).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(api.deleteLoan).toHaveBeenCalledWith("prop-1", "loan-1");
    expect(await screen.findByText("Loan deleted")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
    expect(await screen.findByText("No loans yet")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps the confirm dialog open and reports failure for a loan with overrides", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      listLoans: vi
        .fn()
        .mockResolvedValue([loan({ interest_overrides: { "2024": "100.00" } })]),
      deleteLoan: vi.fn().mockRejectedValue(new ApiError(500, "boom", null)),
    });
    renderPage(api);

    await user.click(
      (await screen.findAllByRole("button", { name: "Delete Main mortgage" }))[0],
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(
      await screen.findByText("Could not delete the loan"),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getAllByText("Main mortgage").length).toBeGreaterThan(0);
    expect(screen.queryByText("Loan deleted")).not.toBeInTheDocument();
  });

  it("shows an error toast and no Undo when an undoable delete fails", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      listLoans: vi.fn().mockResolvedValue([loan()]),
      deleteLoan: vi.fn().mockRejectedValue(new ApiError(500, "boom", null)),
    });
    renderPage(api);

    await user.click(
      (await screen.findAllByRole("button", { name: "Delete Main mortgage" }))[0],
    );

    expect(
      await screen.findByText("Could not delete the loan"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Main mortgage").length).toBeGreaterThan(0);
  });
});

describe("LoansPage — line 12 impact failure", () => {
  it("does not block the page when the impact load fails", async () => {
    const api = makeApi({
      listLoans: vi.fn().mockResolvedValue([loan()]),
      getLine12Impact: vi.fn().mockRejectedValue(new ApiError(500, "boom", null)),
    });
    renderPage(api);

    await screen.findAllByText("Main mortgage");
    expect(addButton()).toBeInTheDocument();
    expect(screen.getByRole("note")).toBeInTheDocument();
    expect(api.getLine12Impact).toHaveBeenCalledWith("prop-1");
  });
});

describe("LoansPage — accessibility (Req 9.20)", () => {
  it("has no axe violations with loans listed", async () => {
    const api = makeApi({
      listLoans: vi.fn().mockResolvedValue([loan()]),
    });
    const { container } = renderPage(api);
    await screen.findAllByText("Main mortgage");

    const results = await axe(container, {
      // jsdom cannot compute colors; contrast stays a manual-AT check.
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });

  it("has no axe violations with a schedule and override-only row shown", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      listLoans: vi.fn().mockResolvedValue([loan()]),
      getLoanSchedule: vi
        .fn()
        .mockResolvedValue(schedule([overrideOnly(2020, "7010.12"), yearly(2023)])),
    });
    const { container } = renderPage(api);
    await user.click(
      (await screen.findAllByRole("button", { name: "Select Main mortgage" }))[0],
    );
    await screen.findAllByText("Override only");

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});

describe("LoansPage — discard changes (Req 10.2-10.7)", () => {
  type Closer = (user: ReturnType<typeof userEvent.setup>) => Promise<void>;
  const closers: Array<[string, Closer]> = [
    [
      "Escape",
      async (user) => {
        await user.keyboard("{Escape}");
      },
    ],
    [
      "backdrop",
      async () => {
        await tick();
        fireEvent.pointerDown(document.body);
      },
    ],
    [
      "Cancel",
      async (user) => {
        await user.click(
          within(modalDialog()).getByRole("button", { name: "Cancel" }),
        );
      },
    ],
  ];

  it.each(closers)(
    "prompts 'Discard changes?' when closing an edited form via %s",
    async (_name, close) => {
      const user = userEvent.setup();
      const api = makeApi();
      renderPage(api);
      await openAddFromEmpty(user);
      await user.type(screen.getByLabelText("Description"), "Second home");

      await close(user);

      expect(
        await screen.findByRole("dialog", { name: "Discard changes?" }),
      ).toBeInTheDocument();
      expect(api.createLoan).not.toHaveBeenCalled();

      // Keep editing retains the edit; Discard then closes the modal.
      await user.click(screen.getByRole("button", { name: "Keep editing" }));
      expect(
        screen.queryByRole("dialog", { name: "Discard changes?" }),
      ).not.toBeInTheDocument();
      expect(screen.getByLabelText("Description")).toHaveValue("Second home");

      await close(user);
      await user.click(await screen.findByRole("button", { name: "Discard" }));
      await waitFor(() =>
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
      );
    },
  );

  it.each(closers)(
    "does not prompt via %s after the edit is restored to the original value",
    async (_name, close) => {
      const user = userEvent.setup();
      renderPage(makeApi({ listLoans: vi.fn().mockResolvedValue([loan()]) }));
      await user.click(
        (await screen.findAllByRole("button", { name: "Edit Main mortgage" }))[0],
      );
      await screen.findByRole("dialog", { name: "Edit loan" });
      const description = screen.getByLabelText("Description");
      await user.type(description, "X");
      await user.type(description, "{Backspace}");
      expect(description).toHaveValue("Main mortgage");

      await close(user);

      await waitFor(() =>
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
      );
      expect(screen.queryByText("Discard changes?")).not.toBeInTheDocument();
    },
  );

  it("closes after a successful save without the prompt", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      createLoan: vi
        .fn()
        .mockResolvedValue(loan({ id: "loan-2", description: "New loan" })),
    });
    renderPage(api);
    await openAddFromEmpty(user);
    await fillValid(user);
    await user.click(submitButton());

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(api.createLoan).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Discard changes?")).not.toBeInTheDocument();
  });
});

describe("LoansPage: new=1 parameter", () => {
  it("opens the add dialog once after the load", async () => {
    renderPage(makeApi(), "?new=1");
    expect(
      await screen.findByRole("dialog", { name: "Add loan" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });
});
