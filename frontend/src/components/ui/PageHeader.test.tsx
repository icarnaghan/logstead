import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";
import { PageHeader } from "./PageHeader";

describe("PageHeader", () => {
  it("renders a focusable h1 with the default id and no banner landmark", () => {
    render(<PageHeader title="Properties" />);
    const h1 = screen.getByRole("heading", { level: 1, name: "Properties" });
    expect(h1).toHaveAttribute("id", "page-heading");
    expect(h1).toHaveAttribute("tabindex", "-1");
    expect(h1.className).toContain("text-page-title");
    expect(h1.className).toContain("focus:outline-none");
    expect(screen.queryByRole("banner")).not.toBeInTheDocument();
  });

  it("renders the description in the muted token", () => {
    render(<PageHeader title="Loans" description="Track loans." />);
    expect(screen.getByText("Track loans.").className).toContain("text-fg-muted");
  });

  it("omits optional slots when not provided", () => {
    render(<PageHeader title="Loans" />);
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("has no accessibility violations with all slots", async () => {
    const { container } = render(
      <MemoryRouter>
        <PageHeader
          title="Loans"
          description="Track loans."
          actions={<button>Add</button>}
          breadcrumb={[{ label: "Properties", to: "/properties" }, { label: "Loans" }]}
        />
      </MemoryRouter>,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });

  it("honors headingId and renders meta, description, actions, breadcrumb, children", () => {
    render(
      <MemoryRouter>
        <PageHeader
          title="Loans"
          headingId="custom"
          meta="Maple Duplex"
          description="Track loans."
          actions={<button>Add</button>}
          breadcrumb={[{ label: "Properties", to: "/properties" }, { label: "Loans" }]}
        >
          <p>tabs slot</p>
        </PageHeader>
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveAttribute("id", "custom");
    expect(screen.getByText("Maple Duplex")).toBeInTheDocument();
    expect(screen.getByText("Track loans.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument();
    expect(screen.getByText("tabs slot")).toBeInTheDocument();
  });
});
