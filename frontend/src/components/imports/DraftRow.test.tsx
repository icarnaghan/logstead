import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import type { Category, DraftChanges, DraftTransaction } from "../../api/imports";
import { DraftRow } from "./DraftRow";

/**
 * Component tests for a single reviewable draft row in isolation (task 22.3).
 *
 * Covers the draft-review contract: `missing_fields` are surfaced as an alert
 * and the matching inputs are `aria-invalid` (Requirement 6.9); editing then
 * Save calls `onSave` with the changed fields (Requirement 6.7); selecting the
 * "Other" category marks the description required (Requirement 7.4); and Remove
 * calls `onRemove` (Requirement 6.8).
 *
 * Validates: Requirements 6.7, 6.8, 6.9, 7.4
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

function makeDraft(overrides: Partial<DraftTransaction> = {}): DraftTransaction {
  return {
    id: "d1",
    date: "2023-03-02",
    amount: "100.00",
    description: "Plumber",
    type: "expense",
    category_id: "cat-repairs",
    missing_fields: [],
    ...overrides,
  };
}

function setup(
  draft: DraftTransaction,
  overrides: {
    onSave?: (id: string, changes: DraftChanges) => Promise<void>;
    onRemove?: (id: string) => Promise<void>;
  } = {},
) {
  const onSave = overrides.onSave ?? vi.fn(async () => {});
  const onRemove = overrides.onRemove ?? vi.fn(async () => {});
  const user = userEvent.setup();
  render(
    <ul>
      <DraftRow
        draft={draft}
        categories={CATEGORIES}
        onSave={onSave}
        onRemove={onRemove}
      />
    </ul>,
  );
  return { user, onSave, onRemove };
}

describe("DraftRow", () => {
  it("surfaces missing fields as an alert and marks matching inputs aria-invalid (Requirement 6.9)", () => {
    setup(
      makeDraft({
        amount: null,
        category_id: null,
        missing_fields: ["amount", "category_id"],
      }),
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/missing before confirming/i);
    expect(alert).toHaveTextContent(/amount/i);
    expect(alert).toHaveTextContent(/category/i);

    expect(screen.getByLabelText(/amount/i)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByLabelText(/category/i)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    // A field that is not missing is not flagged.
    expect(screen.getByLabelText(/^date$/i)).not.toHaveAttribute("aria-invalid");
  });

  it("does not render the alert when there are no missing fields", () => {
    setup(makeDraft());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("saves edits with the changed fields (Requirement 6.7)", async () => {
    const onSave = vi.fn(async () => {});
    const { user } = setup(
      makeDraft({ amount: null, missing_fields: ["amount"] }),
      { onSave },
    );

    await user.type(screen.getByLabelText(/amount/i), "75.00");
    await user.click(screen.getByRole("button", { name: /save draft/i }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith(
      "d1",
      expect.objectContaining({
        amount: "75.00",
        date: "2023-03-02",
        description: "Plumber",
        type: "expense",
        category_id: "cat-repairs",
      }),
    );
  });

  it("sends null for fields cleared to empty on save", async () => {
    const onSave = vi.fn(async () => {});
    const { user } = setup(makeDraft(), { onSave });

    await user.clear(screen.getByLabelText(/description/i));
    await user.click(screen.getByRole("button", { name: /save draft/i }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith(
      "d1",
      expect.objectContaining({ description: null }),
    );
  });

  it("marks the description required when the Other category is selected (Requirement 7.4)", async () => {
    const { user } = setup(makeDraft({ description: null, category_id: "cat-repairs" }));

    // Repairs does not require a description.
    expect(
      screen.queryByText(/description \(required\)/i),
    ).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/category/i), "cat-other");

    expect(screen.getByText(/description \(required\)/i)).toBeInTheDocument();
    // The empty description is flagged invalid once Other requires it.
    expect(screen.getByLabelText(/description/i)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("removes the draft when Remove is clicked (Requirement 6.8)", async () => {
    const onRemove = vi.fn(async () => {});
    const { user } = setup(makeDraft(), { onRemove });

    await user.click(screen.getByRole("button", { name: /remove/i }));

    await waitFor(() => expect(onRemove).toHaveBeenCalledTimes(1));
    expect(onRemove).toHaveBeenCalledWith("d1");
  });

  it("has no automated accessibility violations with a flagged draft", async () => {
    const onSave = vi.fn(async () => {});
    const onRemove = vi.fn(async () => {});
    const { container } = render(
      <ul>
        <DraftRow
          draft={makeDraft({
            amount: null,
            category_id: null,
            missing_fields: ["amount", "category_id"],
          })}
          categories={CATEGORIES}
          onSave={onSave}
          onRemove={onRemove}
        />
      </ul>,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
