import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { LoadingRegion, Skeleton, TableSkeleton } from "./Skeleton";
import { ResponsiveTable } from "./ResponsiveTable";

describe("Skeleton set", () => {
  it("Skeleton is aria-hidden with motion-safe pulse", () => {
    const { container } = render(<Skeleton />);
    const el = container.firstElementChild!;
    expect(el.getAttribute("aria-hidden")).toBe("true");
    expect(el.className).toContain("motion-reduce:animate-none");
  });

  it("LoadingRegion exposes status, busy, and label", () => {
    render(
      <LoadingRegion label="Loading things">
        <Skeleton />
      </LoadingRegion>,
    );
    const region = screen.getByRole("status", { name: "Loading things" });
    expect(region.getAttribute("aria-busy")).toBe("true");
  });

  it("TableSkeleton defaults to 5 rows", () => {
    const { container } = render(<TableSkeleton columns={3} />);
    expect(container.querySelectorAll(".grid")).toHaveLength(5);
  });

  it("TableSkeleton honors configured row and column counts", () => {
    const { container } = render(<TableSkeleton rows={2} columns={4} />);
    const rows = container.querySelectorAll(".grid");
    expect(rows).toHaveLength(2);
    for (const row of Array.from(rows)) {
      expect(row.children).toHaveLength(4);
    }
  });

  it("has no axe violations for a loading region with a table skeleton", async () => {
    const { container } = render(
      <LoadingRegion label="Loading table">
        <TableSkeleton columns={3} />
      </LoadingRegion>,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });

  it("ResponsiveTable loading renders the skeleton instead of rows", () => {
    render(
      <ResponsiveTable
        caption="c"
        columns={[{ key: "a", header: "A" }]}
        rows={[{ id: "1", cells: { a: "cell-value" } }]}
        loading
      />,
    );
    expect(screen.queryByText("cell-value")).toBeNull();
    expect(screen.getByTestId("table-skeleton")).toBeTruthy();
  });
});
