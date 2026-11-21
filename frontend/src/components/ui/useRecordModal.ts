import { useCallback, useReducer, useRef, useState } from "react";
import type { RefObject } from "react";

import { useDiscardGuard } from "./useDiscardGuard";
import type { DiscardGuard } from "./useDiscardGuard";

/**
 * Modal state for add/edit record flows (Requirements 2.1, 2.2, 3.1, 3.7,
 * 3.8, 4.1, 6.4, 6.5, 8.1). The edited record is derived from the loaded list
 * by id instead of being copied into state.
 */
export type RecordModalState =
  | { mode: "closed" }
  | { mode: "add" }
  | { mode: "edit"; recordId: string };

export type RecordModalAction =
  | { type: "open-add" }
  | { type: "open-edit"; recordId: string }
  | { type: "close" }
  | { type: "record-deleted"; recordId: string };

export function recordModalReducer(
  state: RecordModalState,
  action: RecordModalAction,
): RecordModalState {
  switch (action.type) {
    case "open-add":
      return { mode: "add" };
    case "open-edit":
      return { mode: "edit", recordId: action.recordId };
    case "close":
      return state.mode === "closed" ? state : { mode: "closed" };
    case "record-deleted":
      return state.mode === "edit" && state.recordId === action.recordId
        ? { mode: "closed" }
        : state;
    default:
      return state;
  }
}

export interface UseRecordModalOptions {
  /** Focus target when the trigger element is gone (list heading). */
  fallbackFocusRef: RefObject<HTMLElement | null>;
}

export interface UseRecordModalResult<T extends { id: string }> {
  state: RecordModalState;
  /** True when the modal should render open (add, or edit with a loaded record). */
  open: boolean;
  /** The record being edited, derived from the list by id; null in add mode. */
  editing: T | null;
  openAdd: () => void;
  openEdit: (record: T) => void;
  /** Force close: bypasses the discard guard and resets `dirty`. */
  close: () => void;
  /** True while the form has unsaved edits (Requirement 10.1). */
  dirty: boolean;
  setDirty: (dirty: boolean) => void;
  /** Close, asking for confirmation first when dirty (Requirements 10.2-10.5). */
  requestClose: DiscardGuard["requestClose"];
  /** Pass to `RecordModal.discard`. */
  discard: DiscardGuard["discard"];
  onRecordDeleted: (recordId: string) => void;
  /** Pass to `RecordModal.onCloseAutoFocus`. */
  handleCloseAutoFocus: (event: Event) => void;
}

export function useRecordModal<T extends { id: string }>(
  records: readonly T[],
  options: UseRecordModalOptions,
): UseRecordModalResult<T> {
  const { fallbackFocusRef } = options;
  const [state, dispatch] = useReducer(recordModalReducer, {
    mode: "closed",
  } as RecordModalState);
  const [dirty, setDirty] = useState(false);
  const triggerRef = useRef<Element | null>(null);

  const openAdd = useCallback(() => {
    triggerRef.current = document.activeElement;
    setDirty(false);
    dispatch({ type: "open-add" });
  }, []);

  const openEdit = useCallback((record: T) => {
    triggerRef.current = document.activeElement;
    setDirty(false);
    dispatch({ type: "open-edit", recordId: record.id });
  }, []);

  const close = useCallback(() => {
    setDirty(false);
    dispatch({ type: "close" });
  }, []);

  const { requestClose, discard } = useDiscardGuard({ dirty, onClose: close });

  const onRecordDeleted = useCallback((recordId: string) => {
    setDirty(false);
    dispatch({ type: "record-deleted", recordId });
  }, []);

  const handleCloseAutoFocus = useCallback(
    (event: Event) => {
      event.preventDefault();
      const trigger = triggerRef.current;
      if (trigger instanceof HTMLElement && trigger.isConnected) {
        trigger.focus();
      } else {
        fallbackFocusRef.current?.focus();
      }
    },
    [fallbackFocusRef],
  );

  const editing =
    state.mode === "edit"
      ? (records.find((r) => r.id === state.recordId) ?? null)
      : null;
  const open = state.mode === "add" || (state.mode === "edit" && editing !== null);

  return {
    state,
    open,
    editing,
    openAdd,
    openEdit,
    close,
    dirty,
    setDirty,
    requestClose,
    discard,
    onRecordDeleted,
    handleCloseAutoFocus,
  };
}
