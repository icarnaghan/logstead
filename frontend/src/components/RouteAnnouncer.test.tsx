import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { RouteAnnouncer } from "./RouteAnnouncer";

/** Requirements 5.3-5.7 */
let navigate: ReturnType<typeof useNavigate>;

function Harness({ withH1 = true }: { withH1?: boolean }) {
  navigate = useNavigate();
  return (
    <>
      <button>before</button>
      <main id="main-content">
        {withH1 ? <h1>Page</h1> : <p>No heading</p>}
      </main>
      <RouteAnnouncer />
    </>
  );
}

function setup(withH1 = true) {
  render(
    <MemoryRouter initialEntries={["/a"]}>
      <Harness withH1={withH1} />
    </MemoryRouter>,
  );
}

const go = (to: string) => act(() => void navigate(to));
const status = () => screen.getByRole("status");

describe("RouteAnnouncer", () => {
  beforeEach(() => {
    document.title = "Dashboard - Logstead";
  });
  afterEach(() => {
    document.title = "";
  });

  it("focuses the h1 after a path change", () => {
    setup();
    go("/b");
    expect(screen.getByRole("heading", { level: 1 })).toHaveFocus();
  });

  it("falls back to the main landmark when there is no h1", () => {
    setup(false);
    go("/b");
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("does not move focus on first render", () => {
    setup();
    expect(document.body).toHaveFocus();
    expect(status()).toHaveTextContent("");
  });

  it("does not move focus or announce on hash-only or search-only changes", async () => {
    setup();
    const button = screen.getByRole("button", { name: "before" });
    button.focus();
    go("/a#section");
    go("/a?q=1");
    expect(button).toHaveFocus();
    await new Promise((r) => setTimeout(r, 50));
    expect(status()).toHaveTextContent("");
  });

  it("announces the page title without the app suffix", async () => {
    setup();
    go("/b");
    await waitFor(() => expect(status()).toHaveTextContent("Dashboard"));
    expect(status()).toHaveAttribute("aria-live", "polite");
  });

  it("announces two identical titles in a row", async () => {
    setup();
    go("/b");
    await waitFor(() => expect(status()).toHaveTextContent("Dashboard"));
    go("/c");
    // Cleared synchronously so assistive tech sees a fresh change...
    expect(status()).toHaveTextContent("");
    // ...then the same title is announced again.
    await waitFor(() => expect(status()).toHaveTextContent("Dashboard"));
  });
});
