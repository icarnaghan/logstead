import { useState } from "react";
import {
  Button,
  ErrorSummary,
  FormField,
  Input,
  RecordModal,
  useDiscardGuard,
  useFocusFirstInvalid,
  ModalFormActions,
} from "../ui";
import { useDirtyReporter } from "../../lib/dirty";
import { orderedErrors, type ErrorSummaryItem } from "../../lib/formErrors";
import {
  updateProperty,
  ApiError,
  type Property,
} from "../../api/properties";

interface EditPropertyDialogProps {
  /** The property being edited (used to prefill the form). */
  property: Property;
  /** Controls the dialog's open state (the parent owns it). */
  open: boolean;
  /** Open-state change handler (close resets any transient state). */
  onOpenChange: (open: boolean) => void;
  /** Called with the updated property so the list can refresh its card. */
  onUpdated: (property: Property) => void;
  /** Forwarded to RecordModal to restore focus to the opener on close. */
  onCloseAutoFocus?: (event: Event) => void;
  /** Test seam: update call. Defaults to the real `updateProperty`. */
  update?: (
    id: string,
    input: { name: string; address_text: string; property_type?: string | null },
  ) => Promise<Property>;
}

/** Field-level validation errors keyed by the input field name. */
interface FieldErrors {
  name?: string;
  address_text?: string;
  form?: string;
}

const FIELD_ORDER = ["name", "address_text"] as const;
const FIELD_IDS: Record<(typeof FIELD_ORDER)[number], string> = {
  name: "edit-property-name",
  address_text: "edit-property-address",
};

/**
 * Edit-property flow (basics only: name, address, property type).
 *
 * A controlled {@link RecordModal} holding a small form prefilled from the property.
 * Unlike {@link AddPropertyDialog}, editing deliberately does NOT run address
 * autocomplete or RentCast enrichment — it is a plain edit of the core fields
 * and saves via the existing `updateProperty` (`PUT /properties/{id}`). Stored
 * RentCast `details` are preserved untouched (the update body omits them, so
 * the server keeps whatever was persisted at creation). Server-side 400
 * validation errors carry the offending `field`, rendered adjacent to that
 * input.
 */
export function EditPropertyDialog({
  property,
  open,
  onOpenChange,
  onUpdated,
  onCloseAutoFocus,
  update = updateProperty,
}: EditPropertyDialogProps) {
  const [name, setName] = useState(property.name);
  const [addressText, setAddressText] = useState(property.address_text);
  const [propertyType, setPropertyType] = useState(property.property_type ?? "");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [attempt, setAttempt] = useState(0);

  function resetToProperty() {
    setName(property.name);
    setAddressText(property.address_text);
    setPropertyType(property.property_type ?? "");
    setErrors({});
    setSubmitting(false);
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
      const updated = await update(property.id, {
        name: name.trim(),
        address_text: addressText.trim(),
        property_type: propertyType.trim() || null,
      });
      onUpdated(updated);
      resetToProperty();
      onOpenChange(false);
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
    {
      name: property.name,
      address_text: property.address_text,
      property_type: property.property_type ?? "",
    },
    { name, address_text: addressText, property_type: propertyType },
    setDirty,
  );

  const guard = useDiscardGuard({
    dirty,
    onClose: () => {
      resetToProperty();
      onOpenChange(false);
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
    <RecordModal
      open={open}
      onOpenChange={(next) => {
        if (next) onOpenChange(true);
        else guard.requestClose();
      }}
      title="Edit property"
      description="Update the property's name, address, and type."
      dismissible={!submitting}
      discard={guard.discard}
      onCloseAutoFocus={onCloseAutoFocus}
    >
      <form className="space-y-4" onSubmit={handleSubmit} noValidate>
        <ErrorSummary
          items={summaryItems}
          idFor={(field) => FIELD_IDS[field as keyof typeof FIELD_IDS]}
          headingId="edit-property-errors"
        />

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
          label="Address"
          id={FIELD_IDS.address_text}
          error={errors.address_text}
        >
          {(control) => (
            <Input
              {...control}
              type="text"
              value={addressText}
              onChange={(e) => setAddressText(e.target.value)}
            />
          )}
        </FormField>

        <FormField
          label={
            <>
              Property type <span className="text-fg-subtle">(optional)</span>
            </>
          }
          id="edit-property-type"
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
            {submitting ? "Saving…" : "Save changes"}
          </Button>
        </ModalFormActions>
      </form>
    </RecordModal>
  );
}
