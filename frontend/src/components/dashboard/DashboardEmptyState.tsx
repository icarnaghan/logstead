import { Link } from "react-router-dom";
import { Button } from "../ui";
import { SAMPLE_DATA_LINK_LABEL } from "../../lib/emptyCopy";

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
      <Button asChild variant="primary" className="mt-4">
        <Link to="/properties">Add your first property</Link>
      </Button>
      <div className="mt-3">
        <Button asChild variant="secondary" size="sm">
          <Link to="/profile?focus=backup">{SAMPLE_DATA_LINK_LABEL}</Link>
        </Button>
      </div>
    </div>
  );
}
