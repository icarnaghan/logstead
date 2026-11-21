import { usePropertyContext } from "./PropertyLayout";
import { PropertySectionTabs } from "./PropertySectionTabs";
import { resolvePropertyName } from "./propertyName";
import { PageHeader, type Crumb } from "./ui";
import { useDocumentTitle } from "../lib/useDocumentTitle";

interface PropertySectionProps {
  /**
   * The selected property's id. Optional — when omitted it is read from the
   * shared property context. Used only to build the sub-navigation and
   * breadcrumb ancestor paths, never displayed as user-facing content.
   */
  propertyId?: string;
  /** Page heading for this sub-section. */
  title: string;
  /** Short descriptive text under the heading. */
  description: string;
}

/**
 * Shared layout for the per-property sub-sections (Transactions, Depreciable
 * Assets, Schedule E Report).
 *
 * Reads the shared property context (provided by `PropertyLayout`) to present
 * the property by its human-readable **name** — never its raw UUID
 * (Requirements 2.1, 3.1). Renders a breadcrumb trail
 * `Properties > {property name} > {sub-page}` (Requirement 2.2) above the
 * heading, and the per-property sub-navigation as a labelled `nav` landmark so
 * screen-reader users can distinguish it from the primary navigation, with
 * `aria-current="page"` applied to the active link (Requirements 2.4, 14.1).
 */
export function PropertySection({
  propertyId: propertyIdProp,
  title,
  description,
}: PropertySectionProps) {
  const context = usePropertyContext();
  // Prefer the explicit prop for building paths, but fall back to the context
  // id so the component works whether or not a prop is supplied.
  const propertyId = propertyIdProp || context.propertyId;
  const propertyName = resolvePropertyName(
    context.status,
    context.property?.name,
  );

  useDocumentTitle(`${title} - ${propertyName}`);

  const crumbs: Crumb[] = [
    { label: "Properties", to: "/properties" },
    { label: propertyName, to: `/properties/${propertyId}` },
    { label: title },
  ];

  return (
    <section aria-labelledby="page-heading">
      <PageHeader title={title} meta={propertyName} breadcrumb={crumbs}>
        <PropertySectionTabs propertyId={propertyId} />
      </PageHeader>

      <p className="mt-6 text-fg-muted">{description}</p>
    </section>
  );
}
