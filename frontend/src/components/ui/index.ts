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
export * from "./Button";
export * from "./Input";
export * from "./Card";
export * from "./Select";
export * from "./ConfirmDialog";

// Layout + state primitives.
export * from "./ResponsiveTable";
export * from "./StateBlock";

// Wayfinding primitives.
export * from "./Breadcrumb";

// Toast APIs (provider, hook, and public types).
export {
  ToastProvider,
  ToastContext,
  type ToastVariant,
  type ToastMessage,
  type ToastContextValue,
} from "./toast/ToastProvider";
export { useToast } from "./toast/useToast";
