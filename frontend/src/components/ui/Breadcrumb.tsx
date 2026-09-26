import { Fragment } from "react";
import { Link } from "react-router-dom";
import { cn } from "../../lib/cn";
import { FOCUS_RING } from "./focusRing";

export interface Crumb {
  /** Visible label for this crumb. */
  label: string;
  /**
   * Destination path. When omitted, this crumb is the current page and renders
   * as plain text with `aria-current="page"` instead of a link. Only the last
   * crumb should omit `to`.
   */
  to?: string;
}

export interface BreadcrumbProps {
  /** Ordered crumbs, root first. The final crumb (current page) has no `to`. */
  items: Crumb[];
}

const LINK_CLASSES = cn(
  "rounded-sm text-fg-muted hover:text-accent hover:underline",
  FOCUS_RING,
);

/**
 * Shared breadcrumb primitive (Requirements 2.2, 2.3). Renders
 * `nav[aria-label="Breadcrumb"] > ol`, where each ancestor crumb is a
 * react-router `<Link>` (token colors + canonical focus ring) and the final
 * crumb (no `to`) is plain text marked `aria-current="page"`. Separators are
 * decorative and hidden from assistive technology via `aria-hidden`.
 */
export function Breadcrumb({ items }: BreadcrumbProps) {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center gap-2 text-sm">
        {items.map((item, index) => {
          const isLast = index === items.length - 1;
          return (
            <Fragment key={`${item.label}-${index}`}>
              <li>
                {item.to ? (
                  <Link to={item.to} className={LINK_CLASSES}>
                    {item.label}
                  </Link>
                ) : (
                  <span aria-current="page" className="text-fg">
                    {item.label}
                  </span>
                )}
              </li>
              {isLast ? null : (
                <li aria-hidden="true" className="text-fg-subtle">
                  /
                </li>
              )}
            </Fragment>
          );
        })}
      </ol>
    </nav>
  );
}
