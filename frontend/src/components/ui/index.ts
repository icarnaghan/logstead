/**
 * Barrel export for the shared UI primitives (Requirements 1.1, 1.3, 1.4).
 *
 * Re-exports every primitive, its public types, the canonical focus-ring
 * constant, and the toast APIs so call sites import from a single
 * `components/ui` entry point. Each source file owns a distinct set of export
 * names, so `export *` composes without collisions.
 */

// Canonical focus-ring constant reused by every focusable primitive.
export { FOCUS_RING } from "./focusRing";

// Form + action primitives.
export * from "./Badge";
export * from "./Button";
export * from "./Spinner";
export * from "./Input";
export * from "./MoneyInput";
export * from "./DateInput";
export * from "./FormField";
export * from "./Card";
export * from "./Select";
export * from "./Textarea";
export * from "./ConfirmDialog";
export * from "./RecordModal";
export * from "./ModalFormActions";
export * from "./useRecordModal";
export * from "./useOpenerFocusReturn";
export * from "./useDiscardGuard";
export * from "./ErrorSummary";

// Layout + state primitives.
export * from "./ResponsiveTable";
export * from "./StateBlock";
export * from "./EmptyGuide";
export * from "./Skeleton";
export * from "./RefreshingIndicator";
export * from "./useFirstLoad";

// Decorative inline SVG icons.
export * from "./icons";

// Wayfinding primitives.
export * from "./Breadcrumb";
export * from "./PageHeader";

// Toast APIs (provider, hook, and public types).
export {
  ToastProvider,
  ToastContext,
  type ToastVariant,
  type ToastMessage,
  type ToastContextValue,
} from "./toast/ToastProvider";
export { useToast } from "./toast/useToast";
export {
  useUndoableDelete,
  type UndoableDeleteOptions,
} from "./toast/useUndoableDelete";
