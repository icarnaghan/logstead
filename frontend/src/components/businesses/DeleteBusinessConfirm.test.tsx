import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DeleteBusinessConfirm } from "./DeleteBusinessConfirm";
import { ApiError } from "../../api/businesses";

const BUSINESS = { id: "biz-1", legal_name: "Acme Holdings LLC" };

async function openDialog() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /^delete$/i }));
  return user;
}

describe("DeleteBusinessConfirm — happy path (Req 11.6)", () => {
  it("confirm triggers del and calls onDeleted with the id", async () => {
    const del = vi.fn(async () => undefined);
    const onDeleted = vi.fn();
    render(
      <DeleteBusinessConfirm business={BUSINESS} onDeleted={onDeleted} del={del} />,
    );

    const user = await openDialog();
    // The dialog names the business being deleted.
    expect(screen.getByText(/Acme Holdings LLC/)).toBeInTheDocument();

    // The confirm (danger) button inside the dialog.
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: /^delete$/i }),
    );

    await waitFor(() => expect(del).toHaveBeenCalledWith("biz-1"));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("biz-1"));
    // On success the dialog closes.
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });
});

describe("DeleteBusinessConfirm — 409 conflict (Req 5.2, 11.6)", () => {
  it("renders the backend conflict message in an alert and does not call onDeleted", async () => {
    const message =
      "Reassign or unlink the 2 properties linked to this business before deleting it.";
    const del = vi.fn(async () => {
      throw new ApiError(409, message, { error: "conflict", message });
    });
    const onDeleted = vi.fn();
    render(
      <DeleteBusinessConfirm business={BUSINESS} onDeleted={onDeleted} del={del} />,
    );

    const user = await openDialog();
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: /^delete$/i }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(message);
    expect(onDeleted).not.toHaveBeenCalled();
    // The dialog stays open so the user can go unlink the properties.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("falls back to the ApiError message when the body carries no message", async () => {
    const del = vi.fn(async () => {
      throw new ApiError(409, "Business still has linked properties.", null);
    });
    render(
      <DeleteBusinessConfirm business={BUSINESS} onDeleted={vi.fn()} del={del} />,
    );

    const user = await openDialog();
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: /^delete$/i }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/still has linked properties/i);
  });
});

describe("DeleteBusinessConfirm — other errors", () => {
  it("surfaces a generic failure message and keeps the dialog open", async () => {
    const del = vi.fn(async () => {
      throw new ApiError(500, "boom", null);
    });
    const onDeleted = vi.fn();
    render(
      <DeleteBusinessConfirm business={BUSINESS} onDeleted={onDeleted} del={del} />,
    );

    const user = await openDialog();
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: /^delete$/i }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/something went wrong/i);
    expect(onDeleted).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("DeleteBusinessConfirm — accessibility (Req 12.4)", () => {
  it("has no detectable axe violations with the conflict alert showing", async () => {
    const message = "Reassign or unlink the properties first.";
    const del = vi.fn(async () => {
      throw new ApiError(409, message, { message });
    });
    const { container } = render(
      <DeleteBusinessConfirm business={BUSINESS} onDeleted={vi.fn()} del={del} />,
    );

    const user = await openDialog();
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: /^delete$/i }),
    );
    await screen.findByRole("alert");

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});

beforeEach(() => {
  vi.restoreAllMocks();
});
