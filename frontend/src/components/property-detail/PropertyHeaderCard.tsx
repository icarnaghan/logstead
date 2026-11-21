import type { Property } from "../../api/properties";
import { Card } from "../ui";
import { TaxYearSelector } from "../dashboard/TaxYearSelector";

/** Header card: photo + address + type + tax-year selector. */
export function PropertyHeaderCard({
  property,
  photo,
  onOpenPhoto,
  taxYear,
  years,
  onTaxYearChange,
}: {
  property: Property;
  photo: string | null;
  onOpenPhoto: () => void;
  taxYear: number;
  years: readonly number[];
  onTaxYearChange: (year: number) => void;
}) {
  return (
    <Card className="mt-3 flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-4">
        <div className="h-20 w-28 shrink-0 overflow-hidden rounded-md bg-surface-muted">
          {photo ? (
            <button
              type="button"
              onClick={onOpenPhoto}
              aria-label={`View photo of ${property.name} larger`}
              className="block h-full w-full focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
            >
              <img
                src={photo}
                alt={property.name}
                className="h-full w-full object-cover"
              />
            </button>
          ) : (
            <div
              aria-hidden="true"
              className="flex h-full w-full items-center justify-center text-fg-subtle"
            >
              <svg
                viewBox="0 0 24 24"
                className="h-8 w-8"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M3 10.5 12 3l9 7.5" />
                <path d="M5 9.5V21h14V9.5" />
                <path d="M9.5 21v-6h5v6" />
              </svg>
            </div>
          )}
        </div>
        <div>
          <p className="text-fg-muted">{property.address_text}</p>
          {property.property_type ? (
            <p className="mt-1 text-sm text-fg-subtle">
              {property.property_type}
            </p>
          ) : null}
        </div>
      </div>
      <TaxYearSelector
        value={taxYear}
        years={years}
        onChange={onTaxYearChange}
      />
    </Card>
  );
}
