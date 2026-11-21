import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SyncTotalDialog } from "./SyncTotalDialog";

function renderDialog(taxYear: number, onConfirm = vi.fn()) {
  const onOpenChange = vi.fn();
  render(
    <SyncTotalDialog
      open
      onOpenChange={onOpenChange}
      onConfirm={onConfirm}
      label="Repairs"
      line={14}
      taxYear={taxYear}
      enteredTotal="4200.00"
      itemizedSum="5000.00"
      itemizedCount={1}
      currentYear={2025}
    />,
  );
  return { onConfirm, onOpenChange };
}

describe("SyncTotalDialog (Req 9.3, 9.4, 9.9)", () => {
  it("names line, year, both totals, and a signed positive difference", () => {
    renderDialog(2025);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(
      "Schedule E line 14 for 2025 will change from $4,200.00 to $5,000.00 (+$800.00)",
    );
    expect(dialog).toHaveTextContent("sum of your 1 itemized entry");
  });

  it("warns about the filed return for a completed year", () => {
    renderDialog(2024);
    expect(screen.getByRole("dialog")).toHaveTextContent(
      "2024 is a completed tax year. If you already filed a return for it, your records will no longer match the filed return.",
    );
  });

  it("omits the warning for the current year", () => {
    renderDialog(2025);
    expect(screen.getByRole("dialog")).not.toHaveTextContent(/completed tax year/);
  });

  it("confirm calls onConfirm, Cancel does not", async () => {
    const user = userEvent.setup();
    const { onConfirm } = renderDialog(2024);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onConfirm).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Update total" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
