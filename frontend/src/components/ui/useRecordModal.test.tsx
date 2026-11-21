import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useRecordModal } from "./useRecordModal";

interface Rec {
  id: string;
  name: string;
}

const records: Rec[] = [
  { id: "a", name: "Alpha" },
  { id: "b", name: "Beta" },
];

function setup(list: readonly Rec[] = records) {
  const heading = document.createElement("h2");
  heading.tabIndex = -1;
  document.body.appendChild(heading);
  const hook = renderHook(
    ({ list }) => useRecordModal(list, { fallbackFocusRef: { current: heading } }),
    { initialProps: { list } },
  );
  return { heading, ...hook };
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("useRecordModal", () => {
  it("derives the edited record from the list", () => {
    const { result, rerender } = setup();
    expect(result.current.open).toBe(false);
    act(() => result.current.openEdit(records[0]));
    expect(result.current.open).toBe(true);
    expect(result.current.editing).toEqual(records[0]);

    const updated = [{ id: "a", name: "Alpha 2" }, records[1]];
    rerender({ list: updated });
    expect(result.current.editing).toEqual(updated[0]);
  });

  it("reports open false when the edit target is missing", () => {
    const { result, rerender } = setup();
    act(() => result.current.openEdit(records[0]));
    rerender({ list: [records[1]] });
    expect(result.current.editing).toBeNull();
    expect(result.current.open).toBe(false);
  });

  it("opens add with no editing record", () => {
    const { result } = setup();
    act(() => result.current.openAdd());
    expect(result.current.open).toBe(true);
    expect(result.current.editing).toBeNull();
  });

  it("focuses a connected trigger on close auto focus", () => {
    const { result } = setup();
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    trigger.focus();
    act(() => result.current.openAdd());

    const event = new Event("focus", { cancelable: true });
    result.current.handleCloseAutoFocus(event);
    expect(event.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(trigger);
  });

  it("falls back to the heading when the trigger is detached", () => {
    const { result, heading } = setup();
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    trigger.focus();
    act(() => result.current.openAdd());
    trigger.remove();

    result.current.handleCloseAutoFocus(new Event("focus", { cancelable: true }));
    expect(document.activeElement).toBe(heading);
  });

  describe("discard guard", () => {
    it("starts clean and tracks dirty", () => {
      const { result } = setup();
      act(() => result.current.openAdd());
      expect(result.current.dirty).toBe(false);
      act(() => result.current.setDirty(true));
      expect(result.current.dirty).toBe(true);
    });

    it("requestClose closes immediately when clean", () => {
      const { result } = setup();
      act(() => result.current.openAdd());
      act(() => result.current.requestClose());
      expect(result.current.open).toBe(false);
      expect(result.current.discard.open).toBe(false);
    });

    it("requestClose asks first when dirty; cancel keeps edits, confirm closes", () => {
      const { result } = setup();
      act(() => result.current.openAdd());
      act(() => result.current.setDirty(true));
      act(() => result.current.requestClose());
      expect(result.current.open).toBe(true);
      expect(result.current.discard.open).toBe(true);

      act(() => result.current.discard.onCancel());
      expect(result.current.open).toBe(true);
      expect(result.current.dirty).toBe(true);

      act(() => result.current.requestClose());
      act(() => result.current.discard.onConfirm());
      expect(result.current.open).toBe(false);
      expect(result.current.dirty).toBe(false);
    });

    it("a successful save (close) while dirty never shows the confirmation", () => {
      const { result } = setup();
      act(() => result.current.openAdd());
      act(() => result.current.setDirty(true));
      act(() => result.current.close());
      expect(result.current.open).toBe(false);
      expect(result.current.discard.open).toBe(false);
    });

    it("confirm closes the confirmation as well as the modal", () => {
      const { result } = setup();
      act(() => result.current.openAdd());
      act(() => result.current.setDirty(true));
      act(() => result.current.requestClose());
      expect(result.current.discard.open).toBe(true);
      act(() => result.current.discard.onConfirm());
      expect(result.current.discard.open).toBe(false);
      expect(result.current.open).toBe(false);
    });

    it("cancel hides the confirmation but retains dirty and the open modal", () => {
      const { result } = setup();
      act(() => result.current.openEdit(records[0]));
      act(() => result.current.setDirty(true));
      act(() => result.current.requestClose());
      act(() => result.current.discard.onCancel());
      expect(result.current.discard.open).toBe(false);
      expect(result.current.open).toBe(true);
      expect(result.current.dirty).toBe(true);
    });

    it("close force-closes and resets dirty; openAdd/openEdit reset dirty", () => {
      const { result } = setup();
      act(() => result.current.openAdd());
      act(() => result.current.setDirty(true));
      act(() => result.current.close());
      expect(result.current.open).toBe(false);
      expect(result.current.dirty).toBe(false);

      act(() => result.current.setDirty(true));
      act(() => result.current.openEdit(records[0]));
      expect(result.current.dirty).toBe(false);
      act(() => result.current.setDirty(true));
      act(() => result.current.openAdd());
      expect(result.current.dirty).toBe(false);
    });
  });
});
