// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SearchHit, SearchResponse } from "../../api/search";
import { CommandPalette } from "./CommandPalette";
import { useGlobalSearch } from "./useGlobalSearch";

function hit(kind: string, id: string, title: string, link: string): SearchHit {
  return {
    kind,
    id,
    property_id: "p1",
    title,
    subtitle: "Oak St",
    matched_field: "description",
    link,
    amount: null,
    date: null,
  };
}

function response(overrides: Partial<SearchResponse> = {}): SearchResponse {
  return {
    query: "water",
    truncated: false,
    scanned: 3,
    groups: [
      {
        kind: "transaction",
        total: 7,
        hits: [hit("transaction", "t1", "Water bill", "/properties/p1/transactions?focus=t1")],
      },
      {
        kind: "itemized_entry",
        total: 1,
        hits: [hit("itemized_entry", "r1", "Water heater", "/properties/p1/repairs?focus=r1")],
      },
    ],
    ...overrides,
  };
}

function setup(search: (q: string, o?: { signal?: AbortSignal; limit?: number }) => Promise<SearchResponse>) {
  const onOpenLink = vi.fn();
  render(
    <CommandPalette
      open
      onOpenChange={() => undefined}
      initialQuery=""
      items={[]}
      properties={[]}
      propertiesStatus="loaded"
      onRunItem={() => undefined}
      onPickProperty={() => undefined}
      onCloseAutoFocus={() => undefined}
      onOpenLink={onOpenLink}
      search={search}
    />,
  );
  const input = screen.getByRole("combobox");
  const type = (value: string) => fireEvent.change(input, { target: { value } });
  return { onOpenLink, input, type };
}

async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("palette search", () => {
  it("sends no request below 2 characters", async () => {
    const search = vi.fn(() => Promise.resolve(response()));
    const { type } = setup(search);
    type("w");
    await flush(1000);
    expect(search).not.toHaveBeenCalled();
  });

  it("debounces by 250 ms and requests 5 hits per group", async () => {
    const search = vi.fn((_q: string, _o?: { limit?: number }) => Promise.resolve(response()));
    const { type } = setup(search);
    type("wa");
    await flush(200);
    type("wat");
    await flush(200);
    expect(search).not.toHaveBeenCalled();
    await flush(60);
    expect(search).toHaveBeenCalledTimes(1);
    expect(search.mock.calls[0][0]).toBe("wat");
    expect(search.mock.calls[0][1]?.limit).toBe(5);
  });

  it("aborts the in-flight request when the query changes", async () => {
    const signals: AbortSignal[] = [];
    const search = vi.fn((_q: string, o?: { signal?: AbortSignal }) => {
      if (o?.signal) signals.push(o.signal);
      return new Promise<SearchResponse>(() => undefined);
    });
    const { type } = setup(search);
    type("wat");
    await flush(300);
    expect(signals[0].aborted).toBe(false);
    type("wate");
    expect(signals[0].aborted).toBe(true);
  });

  it("marks the list busy, keeps previous results and shows group labels", async () => {
    let resolveSecond: (r: SearchResponse) => void = () => undefined;
    const search = vi
      .fn()
      .mockResolvedValueOnce(response())
      .mockImplementationOnce(() => new Promise((r) => (resolveSecond = r)));
    const { type } = setup(search);
    type("water");
    await flush(300);

    const listbox = screen.getByRole("listbox");
    expect(listbox).toHaveAttribute("aria-busy", "false");
    expect(screen.getByRole("group", { name: "Transactions" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Repairs" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Water bill/ })).toBeInTheDocument();
    // 7 matches, 1 shown: the group offers "See all results".
    expect(screen.getByRole("option", { name: "See all 7 results" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("2 results");

    type("water b");
    await flush(300);
    expect(screen.getByRole("listbox")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("option", { name: /Water b\s?ill/ })).toBeInTheDocument();

    await act(async () => resolveSecond(response({ groups: [] })));
    expect(screen.getByRole("listbox")).toHaveAttribute("aria-busy", "false");
  });

  it("highlights matches with mark elements and never inserts HTML", async () => {
    const title = "Water <img src=x onerror=alert(1)> bill";
    const search = vi.fn(() =>
      Promise.resolve(
        response({
          groups: [{ kind: "transaction", total: 1, hits: [hit("transaction", "t1", title, "/a")] }],
        }),
      ),
    );
    const { type } = setup(search);
    type("water");
    await flush(300);
    const option = screen.getByRole("option", { name: /Water/ });
    expect(option.querySelector("mark")).toHaveTextContent("Water");
    expect(option.querySelector("img")).toBeNull();
    expect(option).toHaveTextContent(title);
  });

  it("shows the truncation notice", async () => {
    const { type } = setup(() => Promise.resolve(response({ truncated: true })));
    type("water");
    await flush(300);
    expect(
      screen.getByText(
        "Results may be incomplete because your data is large. Narrow your search.",
      ),
    ).toBeInTheDocument();
  });

  it("shows an error with retry and keeps previous results", async () => {
    const search = vi
      .fn()
      .mockResolvedValueOnce(response())
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(response());
    const { type } = setup(search);
    type("water");
    await flush(300);
    type("water b");
    await flush(300);
    expect(screen.getByRole("alert")).toHaveTextContent("Search is unavailable. Try again.");
    expect(screen.getByRole("option", { name: /Water b\s?ill/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await flush(0);
    expect(search).toHaveBeenCalledTimes(3);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("opens a safe link and ignores an unsafe one", async () => {
    const search = vi.fn(() =>
      Promise.resolve(
        response({
          groups: [
            {
              kind: "transaction",
              total: 2,
              hits: [
                hit("transaction", "t1", "Safe one", "/properties/p1"),
                hit("transaction", "t2", "Unsafe one", "//evil.example/x"),
              ],
            },
          ],
        }),
      ),
    );
    const { type, onOpenLink } = setup(search);
    type("one");
    await flush(300);

    fireEvent.click(screen.getByRole("option", { name: /Unsafe one/ }));
    expect(onOpenLink).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("option", { name: /Safe one/ }));
    expect(onOpenLink).toHaveBeenCalledWith("/properties/p1");
  });

  it("offers a link to the search page when nothing matches", async () => {
    const { type, onOpenLink } = setup(() => Promise.resolve(response({ groups: [] })));
    type("zzz q");
    await flush(300);
    expect(screen.getByRole("status")).toHaveTextContent("No results");
    fireEvent.click(screen.getByRole("option", { name: /See all results for "zzz q"/ }));
    expect(onOpenLink).toHaveBeenCalledWith("/search?q=zzz%20q");
  });
});

describe("useGlobalSearch", () => {
  function Probe({ q, search }: { q: string; search: () => Promise<SearchResponse> }) {
    const { status, groups } = useGlobalSearch(q, search);
    return <p data-testid="probe">{`${status}:${groups.length}`}</p>;
  }

  it("clears results when the query drops below 2 characters", async () => {
    const search = () => Promise.resolve(response());
    const { rerender } = render(<Probe q="water" search={search} />);
    await flush(300);
    expect(screen.getByTestId("probe")).toHaveTextContent("loaded:2");
    rerender(<Probe q="w" search={search} />);
    await flush(0);
    expect(screen.getByTestId("probe")).toHaveTextContent("idle:0");
  });

  it.each([
    ["null", null],
    ["no groups", {}],
    ["groups not an array", { groups: "x" }],
    ["group without hits", { groups: [{ kind: "transaction", total: 1 }] }],
  ])("falls into the error state on a malformed response (%s)", async (_name, body) => {
    const search = () => Promise.resolve(body as unknown as SearchResponse);
    render(<Probe q="water" search={search} />);
    await flush(300);
    expect(screen.getByTestId("probe")).toHaveTextContent("error:0");
  });
});
