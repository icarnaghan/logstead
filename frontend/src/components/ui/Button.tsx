import { forwardRef } from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "../../lib/cn";
import { FOCUS_RING } from "./focusRing";

export type ButtonVariant = "primary" | "secondary" | "danger";
export type ButtonSize = "sm" | "md";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Render as a Radix Slot child (e.g. wrap a react-router Link). */
  asChild?: boolean;
}

const BASE_CLASSES =
  "inline-flex items-center justify-center rounded-md font-medium disabled:opacity-50 disabled:pointer-events-none";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-fg hover:bg-accent-hover",
  secondary:
    "border border-border bg-surface text-fg-muted hover:bg-surface-muted",
  danger: "border border-danger text-danger hover:bg-danger-subtle",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-sm",
  md: "px-4 py-2 text-sm",
};

/**
 * Shared button primitive with token-only colors and the canonical focus ring
 * (Requirements 1.1, 1.2, 1.6, 8.5). `asChild` lets callers style a
 * react-router `<Link>` as a button without extra wrappers.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    { variant = "secondary", size = "md", asChild = false, className, ...props },
    ref,
  ) {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(
          BASE_CLASSES,
          VARIANT_CLASSES[variant],
          SIZE_CLASSES[size],
          FOCUS_RING,
          className,
        )}
        {...props}
      />
    );
  },
);
