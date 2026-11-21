import { useSearchParams } from "react-router-dom";
import { useParams } from "react-router-dom";
import { ImportReview } from "../components/imports/ImportReview";
import { PageHeader } from "../components/ui";
import { useDocumentTitle } from "../lib/useDocumentTitle";

/**
 * Page wrapper for the expense-summary import + review flow (task 22.2).
 *
 * It reads `propertyId` from the route params and an optional `taxYear` from
 * the query string (defaulting to the current year), then mounts the
 * self-contained {@link ImportReview} component.
 *
 * NOTE: wiring a route (e.g. `/properties/:propertyId/import`) into the shared
 * router lives in `App.tsx`, which is owned elsewhere — this page is provided so
 * that wiring is a small follow-up. `ImportReview` can also be mounted directly
 * from the transactions area without this page.
 */
export default function ImportReviewPage() {
  useDocumentTitle("Import");
  const { propertyId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const taxYear = Number(
    searchParams.get("taxYear") ?? String(new Date().getFullYear()),
  );

  return (
    <section aria-labelledby="page-heading">
      <PageHeader title="Import" />
      <div className="mt-4">
        <ImportReview propertyId={propertyId} taxYear={taxYear} />
      </div>
    </section>
  );
}
