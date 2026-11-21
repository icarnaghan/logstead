import type { ReactNode } from "react";
import { Breadcrumb, type Crumb } from "./Breadcrumb";

export interface PageHeaderProps {
  /** Page title, rendered as the page `h1`. */
  title: string;
  /** Muted text under the title. */
  description?: ReactNode;
  /** Small line under the title, e.g. the property name. */
  meta?: ReactNode;
  /** End aligned from `sm` up, below the title on narrow viewports. */
  actions?: ReactNode;
  /** Renders a `Breadcrumb` above the title. */
  breadcrumb?: Crumb[];
  /** Slot under the header block, used for section tabs. */
  children?: ReactNode;
  /** Id of the `h1`. Defaults to `page-heading`. */
  headingId?: string;
}

/**
 * Shared page header. Renders a `div` (not `header`) so `main` does not gain a
 * second banner landmark. The `h1` is programmatically focusable so route
 * changes can move focus to it.
 */
export function PageHeader({
  title,
  description,
  meta,
  actions,
  breadcrumb,
  children,
  headingId = "page-heading",
}: PageHeaderProps) {
  return (
    <div>
      {breadcrumb && breadcrumb.length > 0 ? (
        <Breadcrumb items={breadcrumb} />
      ) : null}

      <div
        className={`${breadcrumb && breadcrumb.length > 0 ? "mt-2 " : ""}flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between`}
      >
        <div className="min-w-0">
          <h1
            id={headingId}
            tabIndex={-1}
            className="text-page-title text-fg focus:outline-none"
          >
            {title}
          </h1>
          {meta ? <p className="mt-1 text-sm text-fg-subtle">{meta}</p> : null}
          {description ? (
            <p className="mt-1 text-fg-muted">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="shrink-0">{actions}</div> : null}
      </div>

      {children}
    </div>
  );
}
