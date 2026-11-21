import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { useOpenerFocusReturn } from "../ui";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { AddBusinessDialog } from "./AddBusinessDialog";
import { EditBusinessDialog } from "./EditBusinessDialog";
import { ApiError, type Business } from "../../api/businesses";

/**
 * Component tests for the Add/Edit business dialogs (Requirements 1, 4, 11.3,
 * 12.1-12.4).
 */

function createdBusiness(overrides: Partial<Business> = {}): Business {
  return {
    id: "b1",
    user_id: "u1",
    legal_name: "Maple Holdings",
    entity_type: "llc",
    tax_year_end: "12-31",
    ...overrides,
  };
}

async function openAddDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /add business/i }));
  // Wait for the dialog's required legal-name field to appear.
  return screen.findByLabelText(/legal name/i);
}

describe("AddBusinessDialog — entity type requires explicit selection", () => {
  it("blocks submission and shows an error when no entity type is chosen", async () => {
    const user = userEvent.setup();
    const create = vi.fn();

    render(<AddBusinessDialog onCreated={vi.fn()} create={create} />);

    await openAddDialog(user);
    // Fill the legal name but leave the entity type on its placeholder.
    await user.type(screen.getByLabelText(/legal name/i), "Maple Holdings");
    expect(screen.getByLabelText(/entity type/i)).toHaveValue("");

    await user.click(screen.getByRole("button", { name: /save business/i }));

    // The validation message surfaces as an alert tied to the entity-type input
    // (distinct from the select's non-submittable placeholder option).
    // The error summary repeats the message; the field-level alert is the one
    // wired to the input.
    const alerts = await screen.findAllByRole("alert");
    const alert = alerts.find((a) => a.tagName === "P")!;
    expect(alert).toHaveTextContent(/select an entity type/i);
    expect(screen.getByLabelText(/entity type/i)).toHaveAttribute(
      "aria-describedby",
      alert.id,
    );
    expect(create).not.toHaveBeenCalled();
  });

  it("submits once an entity type is explicitly selected", async () => {
    const user = userEvent.setup();
    const create = vi.fn().mockResolvedValue(createdBusiness());
    const onCreated = vi.fn();

    render(<AddBusinessDialog onCreated={onCreated} create={create} />);

    await openAddDialog(user);
    await user.type(screen.getByLabelText(/legal name/i), "Maple Holdings");
    await user.selectOptions(screen.getByLabelText(/entity type/i), "llc");
    await user.click(screen.getByRole("button", { name: /save business/i }));

    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    const payload = create.mock.calls[0][0];
    expect(payload.legal_name).toBe("Maple Holdings");
    expect(payload.entity_type).toBe("llc");
    // tax_year_end defaults to 12-31 when the user does not touch it.
    expect(payload.tax_year_end).toBe("12-31");
    expect(onCreated).toHaveBeenCalledOnce();
  });
});

describe("AddBusinessDialog — EIN hint is non-blocking", () => {
  it("shows the NN-NNNNNNN placeholder and submits with EIN empty", async () => {
    const user = userEvent.setup();
    const create = vi.fn().mockResolvedValue(createdBusiness());

    render(<AddBusinessDialog onCreated={vi.fn()} create={create} />);

    await openAddDialog(user);
    const ein = screen.getByLabelText(/ein/i);
    expect(ein).toHaveAttribute("placeholder", "NN-NNNNNNN");

    await user.type(screen.getByLabelText(/legal name/i), "Maple Holdings");
    await user.selectOptions(screen.getByLabelText(/entity type/i), "llc");
    // Leave EIN blank.
    await user.click(screen.getByRole("button", { name: /save business/i }));

    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    expect(create.mock.calls[0][0].ein).toBeNull();
  });
});

describe("AddBusinessDialog — state, date, and month/day controls render", () => {
  it("renders the formation state dropdown, date input, and month/day control", async () => {
    const user = userEvent.setup();

    render(<AddBusinessDialog onCreated={vi.fn()} create={vi.fn()} />);

    await openAddDialog(user);

    const stateSelect = screen.getByLabelText(/formation state/i);
    expect(stateSelect.tagName).toBe("SELECT");
    expect(
      within(stateSelect).getByRole("option", { name: /California \(CA\)/i }),
    ).toBeInTheDocument();

    const dateInput = screen.getByLabelText(/formation date/i);
    expect(dateInput).toHaveAttribute("type", "date");

    // Month/day control: a month select defaulted to December plus a day input.
    expect(screen.getByLabelText(/tax year end month/i)).toHaveValue("12");
    expect(screen.getByLabelText(/tax year end day/i)).toHaveValue(31);
  });

  it("stores the chosen state code and month/day on submit", async () => {
    const user = userEvent.setup();
    const create = vi.fn().mockResolvedValue(createdBusiness());

    render(<AddBusinessDialog onCreated={vi.fn()} create={create} />);

    await openAddDialog(user);
    await user.type(screen.getByLabelText(/legal name/i), "Oak Partners");
    await user.selectOptions(screen.getByLabelText(/entity type/i), "s_corporation");
    await user.selectOptions(screen.getByLabelText(/formation state/i), "CA");
    await user.selectOptions(screen.getByLabelText(/tax year end month/i), "06");
    const day = screen.getByLabelText(/tax year end day/i);
    await user.clear(day);
    await user.type(day, "30");
    await user.click(screen.getByRole("button", { name: /save business/i }));

    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    const payload = create.mock.calls[0][0];
    expect(payload.formation_state).toBe("CA");
    expect(payload.tax_year_end).toBe("06-30");
  });
});

describe("AddBusinessDialog — server 400 renders beside its field", () => {
  it("maps a legal_name field error onto that input", async () => {
    const user = userEvent.setup();
    const create = vi
      .fn()
      .mockRejectedValue(
        new ApiError(400, "bad request", {
          field: "legal_name",
          message: "That legal name is already in use.",
        }),
      );

    render(<AddBusinessDialog onCreated={vi.fn()} create={create} />);

    await openAddDialog(user);
    await user.type(screen.getByLabelText(/legal name/i), "Maple Holdings");
    await user.selectOptions(screen.getByLabelText(/entity type/i), "llc");
    await user.click(screen.getByRole("button", { name: /save business/i }));

    // Appears in both the error summary and beside the field.
    const matches = await screen.findAllByText(/already in use/i);
    const alert = matches.find((m) => m.tagName === "P")!;
    expect(alert).toBeInTheDocument();
    // The error is wired to the legal-name input via aria-describedby.
    const legalName = screen.getByLabelText(/legal name/i);
    expect(legalName).toHaveAttribute("aria-invalid", "true");
    expect(legalName).toHaveAttribute("aria-describedby", alert.id);
  });
});

describe("AddBusinessDialog — RecordModal behavior (Req 9.1, 9.6-9.9, 10.2)", () => {
  it("opens as a dialog from the built-in trigger", async () => {
    const user = userEvent.setup();
    render(<AddBusinessDialog onCreated={vi.fn()} create={vi.fn()} />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await openAddDialog(user);
    expect(
      screen.getByRole("dialog", { name: /add a business/i }),
    ).toBeInTheDocument();
  });

  it("renders no trigger when controlled", () => {
    render(
      <AddBusinessDialog
        open={false}
        onOpenChange={vi.fn()}
        onCreated={vi.fn()}
        create={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /add business/i }),
    ).not.toBeInTheDocument();
  });

  it("closes and notifies the caller after a successful create", async () => {
    const user = userEvent.setup();
    const created = createdBusiness();
    const create = vi.fn().mockResolvedValue(created);
    const onCreated = vi.fn();

    render(<AddBusinessDialog onCreated={onCreated} create={create} />);

    await openAddDialog(user);
    await user.type(screen.getByLabelText(/legal name/i), "Maple Holdings");
    await user.selectOptions(screen.getByLabelText(/entity type/i), "llc");
    await user.click(screen.getByRole("button", { name: /save business/i }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("keeps the dialog open and retains values when create fails", async () => {
    const user = userEvent.setup();
    const create = vi.fn().mockRejectedValue(new ApiError(500, "server error", null));
    const onCreated = vi.fn();

    render(<AddBusinessDialog onCreated={onCreated} create={create} />);

    await openAddDialog(user);
    await user.type(screen.getByLabelText(/legal name/i), "Maple Holdings");
    await user.selectOptions(screen.getByLabelText(/entity type/i), "llc");
    await user.click(screen.getByRole("button", { name: /save business/i }));

    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    expect(await screen.findAllByText(/server error/i)).not.toHaveLength(0);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText(/legal name/i)).toHaveValue("Maple Holdings");
    expect(screen.getByLabelText(/entity type/i)).toHaveValue("llc");
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("closes immediately without a prompt when the form is pristine", async () => {
    const user = userEvent.setup();
    render(<AddBusinessDialog onCreated={vi.fn()} create={vi.fn()} />);

    await openAddDialog(user);
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(screen.queryByText(/discard changes/i)).not.toBeInTheDocument();
  });

  it("prompts before discarding a dirty form, and keeps values on Keep editing", async () => {
    const user = userEvent.setup();
    render(<AddBusinessDialog onCreated={vi.fn()} create={vi.fn()} />);

    await openAddDialog(user);
    await user.type(screen.getByLabelText(/legal name/i), "Maple");
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(await screen.findByText(/discard changes\?/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /keep editing/i }));
    await waitFor(() =>
      expect(screen.queryByText(/discard changes\?/i)).not.toBeInTheDocument(),
    );
    expect(screen.getByLabelText(/legal name/i)).toHaveValue("Maple");

    await user.click(screen.getByRole("button", { name: /cancel/i }));
    await user.click(await screen.findByRole("button", { name: /^discard$/i }));
    await waitFor(() =>
      expect(screen.queryByLabelText(/legal name/i)).not.toBeInTheDocument(),
    );
  });
});

describe("AddBusinessDialog — accessibility", () => {
  it("contains focus within the open dialog", async () => {
    const user = userEvent.setup();

    render(<AddBusinessDialog onCreated={vi.fn()} create={vi.fn()} />);

    await openAddDialog(user);
    const dialog = screen.getByRole("dialog");
    // Focus starts inside the dialog.
    expect(dialog.contains(document.activeElement)).toBe(true);

    // Tabbing through every control keeps focus trapped within the dialog.
    for (let i = 0; i < 15; i += 1) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });

  it("has no axe violations when open", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <AddBusinessDialog onCreated={vi.fn()} create={vi.fn()} />,
    );

    await openAddDialog(user);

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});

describe("EditBusinessDialog", () => {
  const existing = createdBusiness({
    legal_name: "Maple Holdings",
    entity_type: "s_corporation",
    ein: "12-3456789",
    formation_state: "CA",
    formation_date: "2020-01-15",
    tax_year_end: "06-30",
    business_address: "1 Maple St",
    note: "primary entity",
  });

  it("prefills every field from the business", async () => {
    render(
      <EditBusinessDialog
        business={existing}
        open
        onOpenChange={vi.fn()}
        onUpdated={vi.fn()}
        update={vi.fn()}
      />,
    );

    expect(await screen.findByLabelText(/legal name/i)).toHaveValue("Maple Holdings");
    expect(screen.getByLabelText(/entity type/i)).toHaveValue("s_corporation");
    expect(screen.getByLabelText(/ein/i)).toHaveValue("12-3456789");
    expect(screen.getByLabelText(/formation state/i)).toHaveValue("CA");
    expect(screen.getByLabelText(/formation date/i)).toHaveValue("2020-01-15");
    expect(screen.getByLabelText(/tax year end month/i)).toHaveValue("06");
    expect(screen.getByLabelText(/tax year end day/i)).toHaveValue(30);
  });

  it("submits the updated fields via the update seam", async () => {
    const user = userEvent.setup();
    const update = vi.fn().mockResolvedValue(createdBusiness());
    const onUpdated = vi.fn();

    render(
      <EditBusinessDialog
        business={existing}
        open
        onOpenChange={vi.fn()}
        onUpdated={onUpdated}
        update={update}
      />,
    );

    const legalName = await screen.findByLabelText(/legal name/i);
    await user.clear(legalName);
    await user.type(legalName, "Maple Group");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(update).toHaveBeenCalledOnce());
    expect(update.mock.calls[0][0]).toBe("b1");
    expect(update.mock.calls[0][1].legal_name).toBe("Maple Group");
    expect(onUpdated).toHaveBeenCalledOnce();
  });

  it("surfaces a server 400 entity_type error beside the field", async () => {
    const user = userEvent.setup();
    const update = vi
      .fn()
      .mockRejectedValue(
        new ApiError(400, "bad request", {
          field: "entity_type",
          message: "Unknown entity type.",
        }),
      );

    render(
      <EditBusinessDialog
        business={existing}
        open
        onOpenChange={vi.fn()}
        onUpdated={vi.fn()}
        update={update}
      />,
    );

    await screen.findByLabelText(/legal name/i);
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    // The message appears in the error summary and beside the field.
    const matches = await screen.findAllByText(/unknown entity type/i);
    const alert = matches.find((m) => m.tagName === "P")!;
    const entityType = screen.getByLabelText(/entity type/i);
    expect(entityType).toHaveAttribute("aria-invalid", "true");
    expect(entityType).toHaveAttribute("aria-describedby", alert.id);
  });

  it("opens as a dialog with prefilled values (Req 9.1)", async () => {
    render(
      <EditBusinessDialog
        business={existing}
        open
        onOpenChange={vi.fn()}
        onUpdated={vi.fn()}
        update={vi.fn()}
      />,
    );
    const dialog = await screen.findByRole("dialog", { name: "Edit business" });
    expect(within(dialog).getByLabelText(/legal name/i)).toHaveValue("Maple Holdings");
  });

  it("closes and notifies the caller after a successful save (Req 9.6)", async () => {
    const user = userEvent.setup();
    const saved = createdBusiness({ legal_name: "Maple Group" });
    const update = vi.fn().mockResolvedValue(saved);
    const onUpdated = vi.fn();
    const onOpenChange = vi.fn();

    render(
      <EditBusinessDialog
        business={existing}
        open
        onOpenChange={onOpenChange}
        onUpdated={onUpdated}
        update={update}
      />,
    );

    const legalName = await screen.findByLabelText(/legal name/i);
    await user.clear(legalName);
    await user.type(legalName, "Maple Group");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(saved));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("keeps the dialog open, retains values, and shows the error inside it on failure (Req 9.7, 9.8)", async () => {
    const user = userEvent.setup();
    const update = vi.fn().mockRejectedValue(new ApiError(500, "server error", null));
    const onUpdated = vi.fn();
    const onOpenChange = vi.fn();

    render(
      <EditBusinessDialog
        business={existing}
        open
        onOpenChange={onOpenChange}
        onUpdated={onUpdated}
        update={update}
      />,
    );

    const legalName = await screen.findByLabelText(/legal name/i);
    await user.clear(legalName);
    await user.type(legalName, "Maple Group");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findAllByText(/server error/i)).not.toHaveLength(0);
    expect(screen.getByLabelText(/legal name/i)).toHaveValue("Maple Group");
    expect(onUpdated).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("prompts before discarding a dirty form (Req 9.9, 10.2)", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(
      <EditBusinessDialog
        business={existing}
        open
        onOpenChange={onOpenChange}
        onUpdated={vi.fn()}
        update={vi.fn()}
      />,
    );

    const legalName = await screen.findByLabelText(/legal name/i);
    await user.type(legalName, " X");
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(await screen.findByText(/discard changes\?/i)).toBeInTheDocument();
    expect(onOpenChange).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /keep editing/i }));
    expect(screen.getByLabelText(/legal name/i)).toHaveValue("Maple Holdings X");

    await user.click(screen.getByRole("button", { name: /cancel/i }));
    await user.click(await screen.findByRole("button", { name: /^discard$/i }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("closes without a prompt when pristine", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(
      <EditBusinessDialog
        business={existing}
        open
        onOpenChange={onOpenChange}
        onUpdated={vi.fn()}
        update={vi.fn()}
      />,
    );

    await screen.findByLabelText(/legal name/i);
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.queryByText(/discard changes/i)).not.toBeInTheDocument();
  });

  it("returns focus to the opener when closed", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [open, setOpen] = useState(false);
      const { rememberOpener, handleCloseAutoFocus } = useOpenerFocusReturn();
      return (
        <>
          <button
            type="button"
            onClick={() => {
              rememberOpener();
              setOpen(true);
            }}
          >
            Open edit
          </button>
          <EditBusinessDialog
            business={existing}
            open={open}
            onOpenChange={setOpen}
            onUpdated={vi.fn()}
            onCloseAutoFocus={handleCloseAutoFocus}
            update={vi.fn()}
          />
        </>
      );
    }
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open edit" });
    await user.click(opener);
    await screen.findByRole("dialog", { name: "Edit business" });
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { hidden: true })).toBeNull(),
    );
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it("has no axe violations when open", async () => {
    const { container } = render(
      <EditBusinessDialog
        business={existing}
        open
        onOpenChange={vi.fn()}
        onUpdated={vi.fn()}
        update={vi.fn()}
      />,
    );

    await screen.findByLabelText(/legal name/i);

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
