/**
 * Pure eligibility rules for keyboard shortcuts (ui-polish Requirements 1.7,
 * 1.8, 7.1 to 7.7, 7.10). No DOM state is read except in `classifyTarget` and
 * `hasBlockingDialog`, which take the element or document as an argument.
 */

export type Platform = "mac" | "other";

export type TargetKind = "editable" | "interactive" | "other";

export interface KeyEventInfo {
  key: string;
  keyCode: number;
  target: TargetKind;
  alt: boolean;
  ctrl: boolean;
  meta: boolean;
  shift: boolean;
  isComposing: boolean;
  repeat: boolean;
  defaultPrevented: boolean;
  blockingDialogOpen: boolean;
}

const INTERACTIVE_ROLES = new Set(["menuitem", "tab", "option", "treeitem"]);
const INTERACTIVE_TAGS = new Set(["BUTTON", "A", "SUMMARY"]);
const EDITABLE_TAGS = new Set(["INPUT", "TEXTAREA", "SELECT"]);

/**
 * Classify a keyboard event target. Inputs, textareas, selects and
 * contenteditable elements are editable; buttons, links, `summary` and
 * elements with an interactive role are interactive; everything else is other.
 */
export function classifyTarget(el: EventTarget | null): TargetKind {
  if (el === null || typeof (el as Element).tagName !== "string") return "other";
  const element = el as HTMLElement;
  const tag = element.tagName.toUpperCase();
  if (EDITABLE_TAGS.has(tag)) return "editable";
  if (element.isContentEditable === true) return "editable";
  const ce = element.getAttribute?.("contenteditable");
  if (ce !== null && ce !== undefined && ce.toLowerCase() !== "false") return "editable";
  if (INTERACTIVE_TAGS.has(tag)) return "interactive";
  const role = element.getAttribute?.("role");
  if (role !== null && role !== undefined && INTERACTIVE_ROLES.has(role)) return "interactive";
  return "other";
}

const BLOCKING_DIALOG_SELECTOR =
  '[role="dialog"][data-state="open"]:not([data-palette]), [role="alertdialog"][data-state="open"]:not([data-palette])';

/** True when an open dialog other than the palette or help dialog exists. */
export function hasBlockingDialog(doc: Document): boolean {
  return doc.querySelector(BLOCKING_DIALOG_SELECTOR) !== null;
}

function isComposing(e: KeyEventInfo): boolean {
  return e.isComposing || e.keyCode === 229;
}

/**
 * A plain-key press is eligible only when the target is not editable, no
 * blocking dialog is open, no Alt, Ctrl or Meta is held, the event is not
 * composing, not repeated and not already default-prevented. Shift is not a
 * blocking modifier because `?` needs it on many layouts.
 */
export function isEligiblePlainKey(e: KeyEventInfo): boolean {
  return (
    e.target !== "editable" &&
    !e.blockingDialogOpen &&
    !e.alt &&
    !e.ctrl &&
    !e.meta &&
    !isComposing(e) &&
    !e.repeat &&
    !e.defaultPrevented
  );
}

/**
 * The palette chord is Cmd+K on macOS and Ctrl+K elsewhere. It is allowed from
 * editable targets but never while a blocking dialog is open.
 */
export function isPaletteChord(e: KeyEventInfo, platform: Platform): boolean {
  if (e.key.toLowerCase() !== "k") return false;
  if (e.blockingDialogOpen) return false;
  if (e.alt || isComposing(e) || e.repeat || e.defaultPrevented) return false;
  return platform === "mac" ? e.meta && !e.ctrl : e.ctrl && !e.meta;
}
