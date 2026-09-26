import type { PropertyDetails } from "../../api/properties";
import { formatMoney } from "../../lib/money";

interface PropertyDetailsViewProps {
  details: PropertyDetails;
  /** Optional heading id so callers can label a surrounding region. */
  headingId?: string;
}

/** Render a boolean presence flag as an accessible Yes/No, or null when unset. */
function yesNo(value?: boolean | null): string | null {
  if (value === null || value === undefined) return null;
  return value ? "Yes" : "No";
}

/** A single definition-list row; renders nothing when the value is absent. */
function Row({ label, value }: { label: string; value?: string | number | null }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <>
      <dt className="text-fg-subtle">{label}</dt>
      <dd className="text-fg">{value}</dd>
    </>
  );
}

/** The latest (highest-year) tax assessment, when any exist. */
function latestAssessment(details: PropertyDetails) {
  const list = details.tax_assessments ?? [];
  if (list.length === 0) return null;
  return list.reduce((latest, cur) => (cur.year > latest.year ? cur : latest));
}

/**
 * Read-only display of a property's RentCast-driven details (Requirements 3.3,
 * 3.8, 12.1). Every field is optional and rendered only when present, so a
 * sparse record shows just what the provider supplied. Money values are
 * formatted from their two-decimal string form (never re-derived from a float).
 * Feature booleans render as Yes/No so they never leak the raw `true`/`false`.
 */
export function PropertyDetailsView({ details, headingId }: PropertyDetailsViewProps) {
  const features = details.features ?? {};
  const assessment = latestAssessment(details);
  const lastSalePrice = formatMoney(details.last_sale_price);
  const hoaFee = formatMoney(details.hoa?.fee);

  return (
    <div className="space-y-4 text-sm" aria-labelledby={headingId}>
      <section>
        <h4 className="font-medium text-fg-muted">Structure</h4>
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          <Row label="Type" value={details.property_type} />
          <Row label="Bedrooms" value={details.bedrooms} />
          <Row label="Bathrooms" value={details.bathrooms} />
          <Row label="Living area (sq ft)" value={details.living_area_sqft} />
          <Row label="Lot size" value={details.lot_size} />
          <Row label="Year built" value={details.year_built} />
          <Row label="Zoning" value={details.zoning} />
          <Row label="Subdivision" value={details.subdivision} />
        </dl>
      </section>

      <section>
        <h4 className="font-medium text-fg-muted">Features</h4>
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          <Row label="Architecture" value={features.architecture_type} />
          <Row label="Exterior" value={features.exterior_type} />
          <Row label="Foundation" value={features.foundation_type} />
          <Row label="Roof" value={features.roof_type} />
          <Row label="View" value={features.view_type} />
          <Row label="Heating" value={yesNo(features.heating)} />
          <Row label="Heating type" value={features.heating_type} />
          <Row label="Cooling" value={yesNo(features.cooling)} />
          <Row label="Cooling type" value={features.cooling_type} />
          <Row label="Garage" value={yesNo(features.garage)} />
          <Row label="Garage spaces" value={features.garage_spaces} />
          <Row label="Garage type" value={features.garage_type} />
          <Row label="Pool" value={yesNo(features.pool)} />
          <Row label="Pool type" value={features.pool_type} />
          <Row label="Fireplace" value={yesNo(features.fireplace)} />
          <Row label="Fireplace type" value={features.fireplace_type} />
          <Row label="Floors" value={features.floor_count} />
          <Row label="Rooms" value={features.room_count} />
          <Row label="Units" value={features.unit_count} />
        </dl>
      </section>

      <section>
        <h4 className="font-medium text-fg-muted">Sale &amp; tax</h4>
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          <Row label="Last sale date" value={details.last_sale_date} />
          <Row label="Last sale price" value={lastSalePrice} />
          <Row label="HOA fee (monthly)" value={hoaFee} />
          {assessment ? (
            <>
              <Row
                label={`Tax assessment (${assessment.year})`}
                value={formatMoney(assessment.value)}
              />
              <Row label="Assessed land" value={formatMoney(assessment.land)} />
              <Row
                label="Assessed improvements"
                value={formatMoney(assessment.improvements)}
              />
            </>
          ) : null}
        </dl>
      </section>
    </div>
  );
}
