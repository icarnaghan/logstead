import { useState } from "react";
import { AddressAutocomplete } from "./AddressAutocomplete";
import { PropertyDetailsView } from "./PropertyDetailsView";
import {
  Button,
  ErrorSummary,
  FormField,
  Input,
  RecordModal,
  Select,
  useDiscardGuard,
  useFocusFirstInvalid,
  ModalFormActions,
} from "../ui";
import { useDirtyReporter } from "../../lib/dirty";
import { orderedErrors, type ErrorSummaryItem } from "../../lib/formErrors";
import {
  createProperty,
  enrichAddress,
  fetchUnitAddresses,
  ApiError,
  type AddressSuggestion,
  type EnrichmentResult,
  type Property,
  type PropertyDetails,
} from "../../api/properties";

interface AddPropertyDialogProps {
  /**
   * Controlled open state. When undefined the dialog owns its state and
   * renders the built-in "Add property" trigger (as before).
   */
  open?: boolean;
  /** Called when the dialog requests to open or close. */
  onOpenChange?: (open: boolean) => void;
  /** Called with the newly created property so the list can refresh. */
  onCreated: (property: Property) => void;
  /** Test seam: enrichment call. Defaults to the real `enrichAddress`. */
  enrich?: (address: string) => Promise<EnrichmentResult>;
  /** Test seam: create call. Defaults to the real `createProperty`. */
  create?: (input: {
    name: string;
    address_text: string;
    property_type?: string | null;
    details?: PropertyDetails | null;
  }) => Promise<Property>;
  /** Optional suggestion fetcher forwarded to the address autocomplete. */
  fetchSuggestions?: (
    q: string,
    signal?: AbortSignal,
  ) => Promise<AddressSuggestion[]>;
  /**
   * Test seam: secondary-address (unit) fetcher. Defaults to the real
   * `fetchUnitAddresses`. Called after a building is selected to populate the
   * optional "Unit" picker.
   */
  fetchUnits?: (
    address: string,
    signal?: AbortSignal,
  ) => Promise<AddressSuggestion[]>;
}

type EnrichPhase =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "found"; details: PropertyDetails }
  | { kind: "not_found"; message: string }
  | { kind: "unavailable"; message: string };

/** Field-level validation errors keyed by the input field name. */
interface FieldErrors {
  name?: string;
  address_text?: string;
  form?: string;
}

/**
 * Add-property flow (Requirements 2.1, 2.2, 3.1, 3.3-3.7).
 *
 * A Radix Dialog holding the add-property form. The address field uses
 * {@link AddressAutocomplete}; selecting a suggestion calls RentCast enrichment
 * and, when a record is found, prefills the editable detail fields
 * (Requirement 3.3). When enrichment returns not_found or unavailable, the
 * dialog shows the provider's message and leaves the fields open for manual
 * entry (Requirements 3.5, 3.6) — creation is never blocked (Requirement 3.7).
 *
 * Submitting posts name + address_text (+ optional type). Server-side 400
 * validation errors carry the offending `field`, which is rendered adjacent to
 * that input (Requirement 2.2).
 */
const FIELD_ORDER = ["address_text", "name"] as const;
const FIELD_IDS: Record<(typeof FIELD_ORDER)[number], string> = {
  address_text: "add-property-address",
  name: "add-property-name",
};
const INITIAL_VALUES = { name: "", address_text: "", property_type: "" };

export function AddPropertyDialog({
  open: openProp,
  onOpenChange,
  onCreated,
  enrich = enrichAddress,
  create = createProperty,
  fetchSuggestions,
  fetchUnits = fetchUnitAddresses,
}: AddPropertyDialogProps) {
  const controlled = openProp !== undefined;
  const [innerOpen, setInnerOpen] = useState(false);
  const open = controlled ? openProp : innerOpen;
  function setOpen(next: boolean) {
    if (!controlled) setInnerOpen(next);
    onOpenChange?.(next);
  }
  const [dirty, setDirty] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [name, setName] = useState("");
  const [addressText, setAddressText] = useState("");
  const [propertyType, setPropertyType] = useState("");
  const [enrichPhase, setEnrichPhase] = useState<EnrichPhase>({ kind: "idle" });
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitting, setSubmitting] = useState(false);
  // The selected building's secondary (unit) addresses and the base building
  // address, used to render the optional "Unit" picker. Empty units → no picker.
  const [units, setUnits] = useState<AddressSuggestion[]>([]);
  const [baseAddress, setBaseAddress] = useState("");

  function resetForm() {
    setName("");
    setAddressText("");
    setPropertyType("");
    setEnrichPhase({ kind: "idle" });
    setErrors({});
    setSubmitting(false);
    setUnits([]);
    setBaseAddress("");
  }

  async function handleSelectAddress(suggestion: AddressSuggestion) {
    const address = suggestion.formatted_address;
    setAddressText(address);
    // Fetch the building's units so we can offer a "Unit" picker. This runs
    // alongside enrichment and degrades to no picker on any failure — it must
    // never break the enrich flow.
    setBaseAddress(address);
    setUnits([]);
    void (async () => {
      try {
        const found = await fetchUnits(address);
        setUnits(Array.isArray(found) ? found : []);
      } catch {
        setUnits([]);
      }
    })();
    await runEnrich(address);
  }

  async function runEnrich(address: string) {
    setEnrichPhase({ kind: "loading" });
    try {
      const result = await enrich(address);
      if (result.status === "found" && result.details) {
        const details = result.details;
        // Prefill editable fields from the enriched record. The user may edit
        // any prefilled value before saving (Requirement 3.4).
        if (details.property_type) setPropertyType(details.property_type);
        if (!name && details.formatted_address) {
          setName(details.formatted_address);
        }
        setEnrichPhase({ kind: "found", details });
      } else if (result.status === "not_found") {
        setEnrichPhase({
          kind: "not_found",
          message:
            result.message ??
            "No property data was found for this address. You can enter the details manually.",
        });
      } else {
        setEnrichPhase({
          kind: "unavailable",
          message:
            result.message ??
            "Property data could not be retrieved. You can enter details manually and try again later.",
        });
      }
    } catch {
      // Enrichment failure must never block creation (Requirement 3.7).
      setEnrichPhase({
        kind: "unavailable",
        message:
          "Property data could not be retrieved. You can enter details manually and try again later.",
      });
    }
  }

  async function handleSelectUnit(fullAddress: string) {
    // Selecting a unit sets the saved address to the full unit label (or the
    // base building for "No specific unit") and re-runs enrichment for that
    // address, since RentCast keys off the saved address.
    setAddressText(fullAddress);
    await runEnrich(fullAddress);
  }

  function validate(): FieldErrors {
    const next: FieldErrors = {};
    if (!name.trim()) next.name = "Name is required.";
    if (!addressText.trim()) next.address_text = "Address is required.";
    return next;
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const clientErrors = validate();
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      setAttempt((n) => n + 1);
      return;
    }
    setErrors({});
    setSubmitting(true);
    try {
      // Persist enriched details when RentCast found a record, so the stored
      // property carries them (enrichment never gates creation — Req 3.7).
      const details =
        enrichPhase.kind === "found" ? enrichPhase.details : undefined;
      const property = await create({
        name: name.trim(),
        address_text: addressText.trim(),
        property_type: propertyType.trim() || null,
        ...(details ? { details } : {}),
      });
      onCreated(property);
      resetForm();
      setOpen(false);
    } catch (err) {
      setSubmitting(false);
      if (err instanceof ApiError && err.status === 400) {
        const body = err.body as { field?: string; message?: string } | null;
        const field = body?.field;
        const message = body?.message ?? "Please correct the highlighted field.";
        if (field === "name" || field === "address_text") {
          setErrors({ [field]: message });
          setAttempt((n) => n + 1);
        } else {
          setErrors({ form: message });
        }
        return;
      }
      setErrors({
        form:
          err instanceof ApiError
            ? err.message
            : "Something went wrong while saving the property.",
      });
    }
  }

  useDirtyReporter(
    INITIAL_VALUES,
    { name, address_text: addressText, property_type: propertyType },
    setDirty,
  );

  const guard = useDiscardGuard({
    dirty,
    onClose: () => {
      resetForm();
      setOpen(false);
    },
  });

  useFocusFirstInvalid({
    errors,
    order: FIELD_ORDER,
    idFor: (field) => FIELD_IDS[field],
    attempt,
  });

  const summaryItems: ErrorSummaryItem[] = [
    ...orderedErrors(errors, FIELD_ORDER),
    ...(errors.form ? [{ message: errors.form }] : []),
  ];

  return (
    <>
      {controlled ? null : (
        <Button type="button" variant="primary" onClick={() => setOpen(true)}>
          Add property
        </Button>
      )}
      <RecordModal
        open={open}
        onOpenChange={(next) => {
          if (next) setOpen(true);
          else guard.requestClose();
        }}
        title="Add a property"
        description="Search for the address to prefill details, or enter everything manually. Details are optional — you can always add them later."
        dismissible={!submitting}
        discard={guard.discard}
      >
        <form className="space-y-4" onSubmit={handleSubmit} noValidate>
          <ErrorSummary
            items={summaryItems}
            idFor={(field) => FIELD_IDS[field as keyof typeof FIELD_IDS]}
            headingId="add-property-errors"
          />

          <FormField
            label="Address"
            id={FIELD_IDS.address_text}
            error={errors.address_text}
          >
            {(control) => (
              <AddressAutocomplete
                id={control.id}
                value={addressText}
                onChange={setAddressText}
                onSelect={handleSelectAddress}
                fetchSuggestions={fetchSuggestions}
                invalid={Boolean(errors.address_text)}
                errorId={control["aria-describedby"]}
              />
            )}
          </FormField>

          {units.length > 0 ? (
            <FormField label="Unit" id="add-property-unit">
              {(control) => (
                <Select
                  {...control}
                  value={addressText}
                  onChange={(e) => {
                    void handleSelectUnit(e.target.value);
                  }}
                  className="w-full"
                >
                  <option value={baseAddress}>No specific unit</option>
                  {units.map((unit) => (
                    <option
                      key={unit.provider_place_id ?? unit.formatted_address}
                      value={unit.formatted_address}
                    >
                      {unit.formatted_address}
                    </option>
                  ))}
                </Select>
              )}
            </FormField>
          ) : null}

          {enrichPhase.kind === "loading" ? (
            <p className="text-sm text-fg-subtle" aria-live="polite">
              Looking up property details…
            </p>
          ) : null}
          {enrichPhase.kind === "found" ? (
            <div className="space-y-2">
              <p
                className="rounded-md bg-success-subtle px-3 py-2 text-sm text-success"
                aria-live="polite"
              >
                Property details found and prefilled below. Review and edit
                anything before saving.
              </p>
              <section
                aria-labelledby="add-property-details-heading"
                className="rounded-md border border-border p-3"
              >
                <h3
                  id="add-property-details-heading"
                  className="text-sm font-semibold text-fg"
                >
                  Property details
                </h3>
                <div className="mt-2">
                  <PropertyDetailsView details={enrichPhase.details} />
                </div>
              </section>
            </div>
          ) : null}
          {enrichPhase.kind === "not_found" || enrichPhase.kind === "unavailable" ? (
            <p
              className="rounded-md bg-warning-subtle px-3 py-2 text-sm text-warning"
              aria-live="polite"
            >
              {enrichPhase.message} You can still save the property.
            </p>
          ) : null}

          <FormField label="Name" id={FIELD_IDS.name} error={errors.name}>
            {(control) => (
              <Input
                {...control}
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            )}
          </FormField>

          <FormField
            label={
              <>
                Property type <span className="text-fg-subtle">(optional)</span>
              </>
            }
            id="add-property-type"
          >
            {(control) => (
              <Input
                {...control}
                type="text"
                value={propertyType}
                onChange={(e) => setPropertyType(e.target.value)}
              />
            )}
          </FormField>

          <ModalFormActions>
            <Button
              type="button"
              variant="secondary"
              onClick={() => guard.requestClose()}
            >
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={submitting}>
              {submitting ? "Saving…" : "Save property"}
            </Button>
          </ModalFormActions>
        </form>
      </RecordModal>
    </>
  );
}
