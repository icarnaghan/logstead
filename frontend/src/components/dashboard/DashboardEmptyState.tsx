import { Link } from "react-router-dom";

interface DashboardEmptyStateProps {
  /**
   * The add-first-property guidance from the API. Falls back to a sensible
   * default when the backend omits it (Requirement 11.4).
   */
  prompt?: string | null;
}

/**
 * Empty-state prompt shown when the user owns no properties (Requirement 11.4).
 *
 * Guides the user to add their first property with a clear call to action
 * linking to the properties page, rather than rendering an empty table.
 */
export function DashboardEmptyState({ prompt }: DashboardEmptyStateProps) {
  const message = prompt?.trim()
    ? prompt
    : "Add your first property to get started.";

  return (
    <div className="mt-6 rounded-lg border border-dashed border-border bg-surface p-8 text-center">
      <p className="text-fg-muted">{message}</p>
      <Link
        to="/properties"
        className="mt-4 inline-block rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg hover:bg-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        Add your first property
      </Link>
    </div>
  );
}
