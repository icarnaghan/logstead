import { forwardRef } from "react";
import { cn } from "../../lib/cn";

export interface CardProps extends React.HTMLAttributes<HTMLElement> {
  /** Element to render as. Defaults to "div". */
  as?: "div" | "section" | "li";
}

const CARD_BASE_CLASSES =
  "rounded-lg border border-border bg-surface shadow-card";

/**
 * Shared elevation-surface primitive with token-only styling, consolidating
 * the `shadow-card` treatment duplicated inline across the app
 * (Requirements 1.3, 8.1, 8.4). Forwards refs + native div props and allows a
 * className override.
 */
export const Card = forwardRef<HTMLElement, CardProps>(function Card(
  { as = "div", className, ...props },
  ref,
) {
  const Comp = as as React.ElementType;
  return <Comp ref={ref} className={cn(CARD_BASE_CLASSES, className)} {...props} />;
});

export interface TileProps {
  title: string;
  headingId: string;
  className?: string;
  children: React.ReactNode;
}

/**
 * Composes `Card` with a labelled heading, replacing the two identical local
 * `Tile` definitions in DashboardPage and PropertyDetailPage (Requirements 1.3,
 * 8.4). Renders a `<section aria-labelledby>` with the heading above a spaced
 * content wrapper.
 */
export function Tile({ title, headingId, className, children }: TileProps) {
  return (
    <Card as="section" aria-labelledby={headingId} className={cn("p-4", className)}>
      <h2 id={headingId} className="text-sm font-medium text-fg-subtle">
        {title}
      </h2>
      <div className="mt-2">{children}</div>
    </Card>
  );
}
