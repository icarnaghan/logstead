import { forwardRef, useEffect } from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "../../lib/cn";
import { FOCUS_RING } from "./focusRing";
import { Spinner } from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
export type ButtonSize = "sm" | "md" | "icon";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Render as a Radix Slot child (e.g. wrap a react-router Link). */
  asChild?: boolean;
  /** Show a centered spinner, keep width, and suppress click/submit. */
  loading?: boolean;
}

const BASE_CLASSES =
  "inline-flex items-center justify-center rounded-md font-medium disabled:opacity-50 disabled:pointer-events-none";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-fg hover:bg-accent-hover",
  secondary:
    "border border-border bg-surface text-fg-muted hover:bg-surface-muted",
  danger: "border border-danger text-danger hover:bg-danger-subtle",
  ghost: "bg-transparent text-fg-muted hover:bg-accent-subtle hover:text-accent",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-sm max-md:min-h-11",
  md: "px-4 py-2 text-sm max-md:min-h-11",
  icon: "h-9 w-9 p-0 max-md:h-11 max-md:w-11",
};

/**
 * Shared button primitive with token-only colors and the canonical focus ring
 * (Requirements 1.1, 1.2, 1.6, 8.5). `asChild` lets callers style a
 * react-router `<Link>` as a button without extra wrappers.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      variant = "secondary",
      size = "md",
      asChild = false,
      loading = false,
      className,
      onClick,
      children,
      ...props
    },
    ref,
  ) {
    const Comp = asChild ? Slot : "button";
    const hasName = Boolean(
      props["aria-label"] || props["aria-labelledby"] || props.title,
    );

    // Development-only warnings, once per mount (Requirement 3.6).
    useEffect(() => {
      if (!import.meta.env.DEV) return;
      if (size === "icon" && !hasName) {
        console.warn(
          'Button: size="icon" needs an aria-label, aria-labelledby, or title for an accessible name.',
        );
      }
      if (loading && asChild) {
        console.warn("Button: `loading` is not supported with `asChild`.");
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const showLoading = loading && !asChild;

    const handleClick = (event: React.MouseEvent<HTMLButtonElement>) => {
      if (showLoading) {
        event.preventDefault();
        return;
      }
      onClick?.(event);
    };

    return (
      <Comp
        ref={ref}
        className={cn(
          BASE_CLASSES,
          VARIANT_CLASSES[variant],
          SIZE_CLASSES[size],
          showLoading && "relative",
          FOCUS_RING,
          className,
        )}
        aria-busy={showLoading ? "true" : undefined}
        onClick={handleClick}
        {...props}
      >
        {showLoading ? (
          <>
            <span className="inline-flex items-center gap-2 opacity-0">
              {children}
            </span>
            <span className="absolute inset-0 grid place-items-center">
              <Spinner />
            </span>
          </>
        ) : (
          children
        )}
      </Comp>
    );
  },
);
