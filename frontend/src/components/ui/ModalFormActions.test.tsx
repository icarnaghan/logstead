import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ModalFormActions } from "./ModalFormActions";

describe("ModalFormActions", () => {
  it("renders a sticky, wrapping action bar that keeps buttons in the form", () => {
    render(
      <form aria-label="demo">
        <ModalFormActions>
          <button type="submit">Save</button>
        </ModalFormActions>
      </form>,
    );
    const bar = screen.getByRole("button", { name: "Save" }).parentElement;
    expect(bar).toHaveClass("sticky", "bottom-0", "flex-wrap");
    expect(screen.getByRole("form", { name: "demo" })).toContainElement(bar);
  });
});
