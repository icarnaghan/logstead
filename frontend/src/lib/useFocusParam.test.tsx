import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { useFocusParam } from "./useFocusParam";

const ROWS = [{ id: "a" }, { id: "b" }];

function Harness({ ready = true }: { ready?: boolean }) {
  useFocusParam(ROWS, ready);
  return (
    <ul>
      {ROWS.map((r) => (
        <li key={r.id} id={`row-${r.id}`} tabIndex={-1}>
          {r.id}
        </li>
      ))}
    </ul>
  );
}

function renderAt(url: string, ready = true) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Harness ready={ready} />
    </MemoryRouter>,
  );
}

describe("useFocusParam", () => {
  it("scrolls to and focuses the named row", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    renderAt("/x?focus=b");
    expect(screen.getByText("b")).toHaveFocus();
    expect(scroll).toHaveBeenCalledWith(
      expect.objectContaining({ block: "center" }),
    );
  });

  it("ignores unknown ids and waits for ready", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    renderAt("/x?focus=zzz");
    renderAt("/x?focus=a", false);
    expect(scroll).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(document.body);
  });
});
