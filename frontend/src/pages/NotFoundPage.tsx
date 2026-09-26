import { Link } from "react-router-dom";

/**
 * Fallback page for unmatched routes.
 */
export default function NotFoundPage() {
  return (
    <section aria-labelledby="page-heading">
      <h1 id="page-heading" className="text-2xl font-semibold text-fg">
        Page not found
      </h1>
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
