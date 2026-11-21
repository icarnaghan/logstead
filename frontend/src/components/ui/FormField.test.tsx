import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { FormField } from "./FormField";
import { Input } from "./Input";

/** Tests for FormField (task 6.4, Requirements 6.1-6.6). */

describe("FormField", () => {
  it("associates the label with the control", () => {
    render(<FormField label="Name">{(c) => <Input {...c} />}</FormField>);
    expect(screen.getByLabelText("Name")).toBeInstanceOf(HTMLInputElement);
  });

  it("links the hint via aria-describedby", () => {
    render(
      <FormField label="Name" hint="Legal name">
        {(c) => <Input {...c} />}
      </FormField>,
    );
    const input = screen.getByLabelText("Name");
    const hint = screen.getByText("Legal name");
    expect(input.getAttribute("aria-describedby")).toBe(hint.id);
  });

  it("hides the required marker from assistive technology and sets aria-required", () => {
    render(
      <FormField label="Name" required>
        {(c) => <Input {...c} />}
      </FormField>,
    );
    const input = screen.getByLabelText(/Name/);
    expect(input).toHaveAttribute("aria-required", "true");
    const marker = screen.getByText("*");
    expect(marker).toHaveAttribute("aria-hidden", "true");
  });

  it("renders an alert error with aria-invalid and describedby", () => {
    render(
      <FormField label="Name" hint="Legal name" error="Required">
        {(c) => <Input {...c} />}
      </FormField>,
    );
    const input = screen.getByLabelText("Name");
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Required");
    expect(input).toHaveAttribute("aria-invalid", "true");
    const ids = input.getAttribute("aria-describedby")!.split(" ");
    expect(ids).toContain(alert.id);
    expect(ids).toContain(screen.getByText("Legal name").id);
  });

  it("omits aria-invalid and aria-required when there is no error or requirement", () => {
    render(<FormField label="Name">{(c) => <Input {...c} />}</FormField>);
    const input = screen.getByLabelText("Name");
    expect(input).not.toHaveAttribute("aria-invalid");
    expect(input).not.toHaveAttribute("aria-required");
    expect(input).not.toHaveAttribute("aria-describedby");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("generates unique ids across two instances", () => {
    render(
      <>
        <FormField label="A">{(c) => <Input {...c} />}</FormField>
        <FormField label="B">{(c) => <Input {...c} />}</FormField>
      </>,
    );
    expect(screen.getByLabelText("A").id).not.toBe(screen.getByLabelText("B").id);
  });

  it("honors explicit ids", () => {
    render(
      <FormField label="Name" id="my-id" errorId="my-err" error="Bad">
        {(c) => <Input {...c} />}
      </FormField>,
    );
    expect(screen.getByLabelText("Name").id).toBe("my-id");
    expect(screen.getByRole("alert").id).toBe("my-err");
  });

  it("has no axe violations in the error state", async () => {
    const { container } = render(
      <FormField label="Name" hint="Hint" error="Bad" required>
        {(c) => <Input {...c} />}
      </FormField>,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
