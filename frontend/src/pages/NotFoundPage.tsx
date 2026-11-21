import { Link } from "react-router-dom";
import { PageHeader } from "../components/ui";
import { useDocumentTitle } from "../lib/useDocumentTitle";

/**
 * Fallback page for unmatched routes.
 */
export default function NotFoundPage() {
  useDocumentTitle("Page not found");

  return (
    <section aria-labelledby="page-heading">
      <PageHeader title="Page not found" />
      <p className="mt-2 text-fg-muted">
        The page you requested does not exist.{" "}
        <Link
          to="/"
          className="text-accent underline underline-offset-2 hover:text-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Return to the dashboard
        </Link>
        .
      </p>
    </section>
  );
}
