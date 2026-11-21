import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import ActivityPage from "./ActivityPage";
import { activityApi, type ActivityEvent } from "../api/activity";
import { ApiError } from "../lib/apiClient";
import { ToastProvider } from "../components/ui";
import { ShellPropertiesProvider } from "../components/ShellPropertiesContext";

function event(id: string, over: Partial<ActivityEvent> = {}): ActivityEvent {
  return {
    id,
    at: "2024-03-07T15:04:00Z",
    action: "create",
    entity: "transaction",
    record_id: `r-${id}`,
    property_id: "p1",
    property_name: "Oak House",
    summary: `Added ${id}`,
    before: null,
    after: { amount: "125.00", description: "Water bill" },
    truncated: false,
    restorable: false,
    restored_as: null,
    ...over,
  };
}

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

function renderPage(url = "/activity") {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <ToastProvider>
        <ShellPropertiesProvider
          load={() =>
            Promise.resolve([{ id: "p1", name: "Oak House" }] as never)
          }
        >
          <ActivityPage />
          <Where />
        </ShellPropertiesProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => vi.restoreAllMocks());

describe("ActivityPage", () => {
  it("renders events with time, badge, summary link, money details and announces the count", async () => {
    vi.spyOn(activityApi, "list").mockResolvedValue({
      events: [event("a")],
      next_cursor: null,
    });
    renderPage();
    const list = await screen.findByRole("list", { name: "Activity events" });
    const item = within(list).getByRole("listitem");
    expect(item.querySelector("time")).toHaveAttribute(
      "datetime",
      "2024-03-07T15:04:00Z",
    );
    expect(within(item).getByText("Created")).toBeInTheDocument();
    expect(within(item).getByRole("link", { name: "Added a" })).toHaveAttribute(
      "href",
      "/properties/p1/transactions?focus=r-a",
    );
    expect(item.querySelector("dl")).toHaveTextContent("$125.00");
    expect(
      screen.getByRole("heading", { level: 1, name: "Activity" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getAllByRole("status").some((n) => n.textContent === "1 event"),
      ).toBe(true),
    );
  });

  it("shows the empty state", async () => {
    vi.spyOn(activityApi, "list").mockResolvedValue({
      events: [],
      next_cursor: null,
    });
    renderPage();
    expect(await screen.findByText("No activity yet")).toBeInTheDocument();
    expect(screen.getByText(/24 months/)).toBeInTheDocument();
  });

  it("loads more with the cursor and appends", async () => {
    const list = vi
      .spyOn(activityApi, "list")
      .mockResolvedValueOnce({ events: [event("a")], next_cursor: "c1" })
      .mockResolvedValueOnce({ events: [event("b")], next_cursor: null });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Load more" }));
    await screen.findByText("Added b");
    expect(screen.getByText("Added a")).toBeInTheDocument();
    expect(list.mock.calls[1][0]).toMatchObject({ cursor: "c1" });
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("uses the property route and writes the property parameter", async () => {
    vi.spyOn(activityApi, "list").mockResolvedValue({
      events: [event("a")],
      next_cursor: null,
    });
    const forProperty = vi
      .spyOn(activityApi, "listForProperty")
      .mockResolvedValue({ events: [event("p")], next_cursor: null });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Added a");
    await screen.findByRole("option", { name: "Oak House" });
    await user.selectOptions(screen.getByLabelText("Property"), "p1");
    await screen.findByText("Added p");
    expect(forProperty).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ entity: null }),
    );
    expect(screen.getByTestId("where")).toHaveTextContent(
      "/activity?property=p1",
    );
  });

  it("passes entity and action filters", async () => {
    const list = vi
      .spyOn(activityApi, "list")
      .mockResolvedValue({ events: [event("a")], next_cursor: null });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Added a");
    await user.selectOptions(screen.getByLabelText("Record type"), "loan");
    await user.selectOptions(screen.getByLabelText("Action"), "delete");
    await waitFor(() =>
      expect(list).toHaveBeenLastCalledWith(
        expect.objectContaining({ entity: "loan", action: "delete" }),
      ),
    );
  });

  it("shows an error with retry", async () => {
    const list = vi
      .spyOn(activityApi, "list")
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({ events: [event("a")], next_cursor: null });
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load activity.",
    );
    await user.click(screen.getByRole("button", { name: /retry/i }));
    await screen.findByText("Added a");
    expect(list).toHaveBeenCalledTimes(2);
  });

  describe("restore", () => {
    const deleted = (over: Partial<ActivityEvent> = {}) =>
      event("d", {
        action: "delete",
        restorable: true,
        record_id: "old",
        summary: "Deleted d",
        ...over,
      });

    function listWith(e: ActivityEvent) {
      vi.spyOn(activityApi, "list").mockResolvedValue({
        events: [e],
        next_cursor: null,
      });
    }

    it("confirms, restores, toasts with a link and marks the row Restored", async () => {
      listWith(deleted());
      const restore = vi
        .spyOn(activityApi, "restore")
        .mockResolvedValue({
          record_id: "new1",
          event_id: "d",
          restored_at: "t",
        });
      const user = userEvent.setup();
      renderPage();
      await user.click(await screen.findByRole("button", { name: "Restore" }));
      const dialog = await screen.findByRole("dialog");
      expect(dialog).toHaveTextContent(/new id/);
      expect(restore).not.toHaveBeenCalled();
      await user.click(within(dialog).getByRole("button", { name: "Restore" }));
      await waitFor(() => expect(restore).toHaveBeenCalledWith("p1", "d"));
      expect(await screen.findByText("Record restored")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Restore" })).toBeNull();
      expect(
        screen.getByRole("link", { name: "View restored record" }),
      ).toHaveAttribute("href", "/properties/p1/transactions?focus=new1");
      await user.click(screen.getByRole("button", { name: /View record/ }));
      expect(screen.getByTestId("where")).toHaveTextContent(
        "/properties/p1/transactions?focus=new1",
      );
    });

    it("offers no Restore for update events, unrestorable or restored deletes", async () => {
      vi.spyOn(activityApi, "list").mockResolvedValue({
        events: [
          event("u", { action: "update", restorable: true }),
          deleted({ id: "x", restorable: false }),
          deleted({ id: "y", restored_as: "n2" }),
        ],
        next_cursor: null,
      });
      renderPage();
      await screen.findByRole("list", { name: "Activity events" });
      expect(screen.queryByRole("button", { name: "Restore" })).toBeNull();
      expect(
        screen.getByRole("link", { name: "View restored record" }),
      ).toBeInTheDocument();
    });

    it("shows a 409 message and marks an already restored event", async () => {
      listWith(deleted());
      vi.spyOn(activityApi, "restore").mockRejectedValue(
        new ApiError(409, "conflict", {
          error: "conflict",
          message: "This event was already restored.",
        }),
      );
      const user = userEvent.setup();
      renderPage();
      await user.click(await screen.findByRole("button", { name: "Restore" }));
      const dialog = await screen.findByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: "Restore" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "already restored",
      );
      expect(screen.queryByRole("button", { name: "Restore" })).toBeNull();
    });

    it("keeps the button after a failed restore", async () => {
      listWith(deleted());
      vi.spyOn(activityApi, "restore").mockRejectedValue(new Error("boom"));
      const user = userEvent.setup();
      renderPage();
      await user.click(await screen.findByRole("button", { name: "Restore" }));
      const dialog = await screen.findByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: "Restore" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Could not restore",
      );
      expect(
        screen.getByRole("button", { name: "Restore" }),
      ).toBeInTheDocument();
    });
  });
});
