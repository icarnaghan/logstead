import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { ApiError } from "../../lib/apiClient";
import type {
  Category,
  ConfirmOutcome,
  DraftTransaction,
} from "../../api/imports";
import { ImportReview, type ImportApi } from "./ImportReview";

/**
 * Component tests for the expense-import review UI (task 22.2 / 22.3).
 *
 * The imports API is fully injected (no network, no real FileReader):
 *  - starting an import lists drafts with missing-field flags (Req 6.5, 6.9)
 *  - editing a draft clears its flag (Req 6.7, 6.9)
 *  - confirm reports converted vs remaining (Req 6.10, 6.11)
 *  - a parse-failure create shows the manual-entry message (Req 6.12)
 *  - a non-PDF is rejected client-side (Req 6.2)
 *
 * Validates: Requirements 6.2, 6.9, 6.11, 6.12
 */

const CATEGORIES: Category[] = [
  {
    id: "cat-repairs",
    kind: "expense",
    label: "Repairs",
    schedule_e_line: 14,
    requires_description: false,
  },
  {
    id: "cat-other",
    kind: "expense",
    label: "Other",
    schedule_e_line: 19,
    requires_description: true,
  },
];

function makeApi(overrides: Partial<ImportApi> = {}): ImportApi {
  return {
    createImport: vi.fn(async () => ({ id: "sess-1" })),
    listDrafts: vi.fn(async () => []),
    updateDraft: vi.fn(
      async (_s, id): Promise<DraftTransaction> => ({
        id,
        date: "2023-05-01",
        amount: "100.00",
        description: "x",
        type: "expense",
        category_id: "cat-repairs",
        missing_fields: [],
      }),
    ),
    removeDraft: vi.fn(async () => {}),
    confirmImport: vi.fn(
      async (): Promise<ConfirmOutcome> => ({
        created_ids: [],
        rejected: [],
        converted_count: 0,
        remaining_incomplete: 0,
        session: {
          id: "sess-1",
          property_id: "p1",
          tax_year: 2023,
          status: "confirmed",
        },
      }),
    ),
    listCategories: vi.fn(async () => CATEGORIES),
    fileToBase64: vi.fn(async () => "QkFTRTY0"),
    ...overrides,
  };
}

/** A File whose `type` is application/pdf. */
function pdfFile(name = "summary.pdf"): File {
  return new File(["%PDF-1.4"], name, { type: "application/pdf" });
}

async function uploadFile(file: File) {
  const user = userEvent.setup();
  const input = screen.getByLabelText(/expense summary pdf/i);
  await user.upload(input, file);
  return user;
}

describe("ImportReview", () => {
  it("starts an import and lists drafts with missing-field flags", async () => {
    const drafts: DraftTransaction[] = [
      {
        id: "d1",
        date: "2023-03-02",
        amount: null,
        description: "Plumber",
        type: "expense",
        category_id: null,
        missing_fields: ["amount", "category_id"],
      },
    ];
    const api = makeApi({ listDrafts: vi.fn(async () => drafts) });

    render(<ImportReview propertyId="p1" taxYear={2023} api={api} />);

    await uploadFile(pdfFile());

    // A draft appears with its missing fields flagged (Req 6.5, 6.9).
    const alert = await screen.findByText(/missing before confirming/i);
    expect(alert).toHaveTextContent(/amount/i);
    expect(alert).toHaveTextContent(/category/i);
    expect(api.createImport).toHaveBeenCalledWith(
      "p1",
      2023,
      expect.objectContaining({ contentType: "application/pdf" }),
    );
  });

  it("rejects a non-PDF file client-side without calling the API", async () => {
    const api = makeApi();
    render(<ImportReview propertyId="p1" taxYear={2023} api={api} />);

    // `userEvent.upload` enforces the `accept` attribute, so drive the change
    // event directly to exercise the component's own client-side guard.
    const input = screen.getByLabelText(/expense summary pdf/i) as HTMLInputElement;
    const nonPdf = new File(["hello"], "notes.txt", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [nonPdf] } });

    expect(
      await screen.findByText(/a pdf file is required/i),
    ).toBeInTheDocument();
    expect(api.createImport).not.toHaveBeenCalled();
  });

  it("shows the manual-entry message when the import fails to parse", async () => {
    const api = makeApi({
      createImport: vi.fn(async () => {
        throw new ApiError(503, "The expense summary could not be parsed.", {});
      }),
    });
    render(<ImportReview propertyId="p1" taxYear={2023} api={api} />);

    await uploadFile(pdfFile());

    const alert = await screen.findByText(/could not be parsed/i);
    expect(alert).toHaveTextContent(/manually/i);
  });

  it("shows the no-line-items manual-entry message when zero drafts parse", async () => {
    const api = makeApi({ listDrafts: vi.fn(async () => []) });
    render(<ImportReview propertyId="p1" taxYear={2023} api={api} />);

    await uploadFile(pdfFile());

    expect(
      await screen.findByText(/no transactions could be extracted/i),
    ).toBeInTheDocument();
  });

  it("clears a draft's flag after editing it to completion", async () => {
    const drafts: DraftTransaction[] = [
      {
        id: "d1",
        date: "2023-03-02",
        amount: null,
        description: "Plumber",
        type: "expense",
        category_id: "cat-repairs",
        missing_fields: ["amount"],
      },
    ];
    const api = makeApi({
      listDrafts: vi.fn(async () => drafts),
      updateDraft: vi.fn(
        async (_s, id): Promise<DraftTransaction> => ({
          id,
          date: "2023-03-02",
          amount: "50.00",
          description: "Plumber",
          type: "expense",
          category_id: "cat-repairs",
          missing_fields: [],
        }),
      ),
    });

    render(<ImportReview propertyId="p1" taxYear={2023} api={api} />);
    const user = await uploadFile(pdfFile());

    expect(
      await screen.findByText(/missing before confirming/i),
    ).toBeInTheDocument();

    const amount = screen.getByLabelText(/amount/i);
    await user.type(amount, "50.00");
    await user.click(screen.getByRole("button", { name: /save draft/i }));

    // The flag is gone after the recomputed draft comes back with no missing.
    await waitFor(() => {
      expect(
        screen.queryByText(/missing before confirming/i),
      ).not.toBeInTheDocument();
    });
    expect(api.updateDraft).toHaveBeenCalledWith(
      "sess-1",
      "d1",
      expect.objectContaining({ amount: "50.00" }),
    );
  });

  it("removes a draft when the remove action is used", async () => {
    const drafts: DraftTransaction[] = [
      {
        id: "d1",
        date: "2023-03-02",
        amount: "10.00",
        description: "A",
        type: "expense",
        category_id: "cat-repairs",
        missing_fields: [],
      },
    ];
    const api = makeApi({ listDrafts: vi.fn(async () => drafts) });
    render(<ImportReview propertyId="p1" taxYear={2023} api={api} />);
    const user = await uploadFile(pdfFile());

    expect(await screen.findByLabelText("Draft transaction")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /remove/i }));

    await waitFor(() => {
      expect(
        screen.queryByLabelText("Draft transaction"),
      ).not.toBeInTheDocument();
    });
    expect(api.removeDraft).toHaveBeenCalledWith("sess-1", "d1");
  });

  it("confirms and reports converted vs remaining and rejections", async () => {
    const drafts: DraftTransaction[] = [
      {
        id: "d1",
        date: "2023-03-02",
        amount: "10.00",
        description: "A",
        type: "expense",
        category_id: "cat-repairs",
        missing_fields: [],
      },
    ];
    const outcome: ConfirmOutcome = {
      created_ids: ["t1"],
      rejected: [
        { draft_id: "d2", message: "Amount must be greater than zero", field: "amount" },
      ],
      converted_count: 1,
      remaining_incomplete: 2,
      session: {
        id: "sess-1",
        property_id: "p1",
        tax_year: 2023,
        status: "review",
      },
    };
    let draftCall = 0;
    const api = makeApi({
      listDrafts: vi.fn(async () => {
        draftCall += 1;
        return draftCall === 1 ? drafts : [];
      }),
      confirmImport: vi.fn(async () => outcome),
    });

    render(<ImportReview propertyId="p1" taxYear={2023} api={api} />);
    const user = await uploadFile(pdfFile());

    await screen.findByLabelText("Draft transaction");
    await user.click(screen.getByRole("button", { name: /confirm import/i }));

    const result = await screen.findByRole("status", { name: undefined });
    // The status region shows converted + remaining counts (Req 6.10, 6.11).
    const resultRegion = screen.getByText(/import result/i).closest("div")!;
    expect(within(resultRegion).getByText(/1 draft converted/i)).toBeTruthy();
    expect(within(resultRegion).getByText(/2 remaining incomplete/i)).toBeTruthy();
    expect(within(resultRegion).getByText(/amount must be greater than zero/i)).toBeTruthy();
    expect(result).toBeTruthy();
  });

  it("has no automated accessibility violations after drafts load", async () => {
    const drafts: DraftTransaction[] = [
      {
        id: "d1",
        date: "2023-03-02",
        amount: null,
        description: "Plumber",
        type: "expense",
        category_id: null,
        missing_fields: ["amount", "category_id"],
      },
    ];
    const api = makeApi({ listDrafts: vi.fn(async () => drafts) });
    const { container } = render(
      <ImportReview propertyId="p1" taxYear={2023} api={api} />,
    );
    await uploadFile(pdfFile());
    await screen.findByLabelText("Draft transaction");

    // Color-contrast checks require canvas (unavailable in jsdom); disable that
    // rule here — contrast is validated in the shell's axe tests / manual AT.
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
