import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { DashboardEmptyState } from "./DashboardEmptyState";

function renderEmptyState(prompt?: string | null) {
  return render(
    <MemoryRouter>
      <DashboardEmptyState prompt={prompt} />
    </MemoryRouter>,
  );
}

describe("DashboardEmptyState (Req 11.4)", () => {
  it("renders the prompt text supplied by the API", () => {
    renderEmptyState("You have no properties yet — add one to begin.");

    expect(
      screen.getByText("You have no properties yet — add one to begin."),
    ).toBeInTheDocument();
  });

  it("falls back to a default message when prompt is null", () => {
    renderEmptyState(null);

    expect(
      screen.getByText(/add your first property to get started/i),
    ).toBeInTheDocument();
  });

  it("falls back to a default message when prompt is undefined", () => {
    renderEmptyState();

    expect(
      screen.getByText(/add your first property to get started/i),
    ).toBeInTheDocument();
  });

  it("falls back to a default message when prompt is blank whitespace", () => {
    renderEmptyState("   ");

    expect(
      screen.getByText(/add your first property to get started/i),
    ).toBeInTheDocument();
  });

  it("renders a call-to-action link to the properties page", () => {
    renderEmptyState("Add your first property to get started.");

    const cta = screen.getByRole("link", {
      name: /add your first property/i,
    });
    expect(cta).toHaveAttribute("href", "/properties");
  });

  it("renders no data table in the empty state", () => {
    renderEmptyState(null);

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
