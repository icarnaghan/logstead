import { StrictMode } from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useNewParam } from "./useNewParam";

function Probe({ open, ready }: { open: () => void; ready: boolean }) {
  useNewParam(open, ready);
  const location = useLocation();
  return <p data-testid="search">{location.search}</p>;
}

function setup(url: string, ready: boolean, strict = false) {
  const open = vi.fn();
  const tree = (
    <MemoryRouter initialEntries={[url]}>
      <Probe open={open} ready={ready} />
    </MemoryRouter>
  );
  const view = render(strict ? <StrictMode>{tree}</StrictMode> : tree);
  return { open, view, tree };
}

describe("useNewParam", () => {
  it("opens once and removes only the new parameter", () => {
    const { open } = setup("/x?new=1&year=2024", true);
    expect(open).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("search").textContent).toBe("?year=2024");
  });

  it("opens once under StrictMode", () => {
    const { open } = setup("/x?new=1", true, true);
    expect(open).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("search").textContent).toBe("");
  });

  it("waits for ready and keeps the parameter until then", () => {
    const { open, view } = setup("/x?new=1", false);
    expect(open).not.toHaveBeenCalled();
    expect(screen.getByTestId("search").textContent).toBe("?new=1");
    view.rerender(
      <MemoryRouter initialEntries={["/x?new=1"]}>
        <Probe open={open} ready />
      </MemoryRouter>,
    );
    expect(open).toHaveBeenCalledTimes(1);
  });

  it("does nothing without new=1", () => {
    const { open } = setup("/x?new=0", true);
    expect(open).not.toHaveBeenCalled();
    expect(screen.getByTestId("search").textContent).toBe("?new=0");
  });
});
