import { useState } from "react";
import {
  Button,
  ErrorSummary,
  RecordModal,
  useDiscardGuard,
  useFocusFirstInvalid,
  ModalFormActions,
} from "../ui";
import { orderedErrors, type ErrorSummaryItem } from "../../lib/formErrors";
import { isDirty } from "../../lib/dirty";
import {
  updateBusiness,
  ApiError,
  type Business,
  type BusinessInput,
} from "../../api/businesses";
import { BusinessFormFields, type BusinessFormState } from "./BusinessFormFields";
import {
  buildBusinessInput,
  fieldErrorsFromBody,
  joinTaxYearEnd,
  splitTaxYearEnd,
  type BusinessFieldErrors,
} from "./businessForm";

interface EditBusinessDialogProps {
  /** The business being edited (used to prefill the form). */
  business: Business;
  /** Controls the dialog's open state (the parent owns it). */
  open: boolean;
  /** Open-state change handler (close resets any transient state). */
  onOpenChange: (open: boolean) => void;
  /** Called with the updated business so the list can refresh its row. */
  onUpdated: (business: Business) => void;
  /** Forwarded to RecordModal to restore focus to the opener on close. */
  onCloseAutoFocus?: (event: Event) => void;
  /** Test seam: update call. Defaults to the real `updateBusiness`. */
  update?: (id: string, input: BusinessInput) => Promise<Business>;
}

const FIELD_ORDER = ["legal_name", "entity_type"] as const;
const ID_PREFIX = "edit-business";
const FIELD_IDS: Record<(typeof FIELD_ORDER)[number], string> = {
  legal_name: `${ID_PREFIX}-legal-name`,
  entity_type: `${ID_PREFIX}-entity-type`,
};
const idFor = (field: string) =>
  FIELD_IDS[field as keyof typeof FIELD_IDS] ?? `${ID_PREFIX}-${field}`;

function formStateFromBusiness(business: Business): BusinessFormState {
  const { month, day } = splitTaxYearEnd(business.tax_year_end);
  return {
    legalName: business.legal_name,
    entityType: business.entity_type,
    ein: business.ein ?? "",
    formationState: business.formation_state ?? "",
    formationDate: business.formation_date ?? "",
    businessAddress: business.business_address ?? "",
    taxYearEndMonth: month,
    taxYearEndDay: day,
    note: business.note ?? "",
  };
}

/**
 * Edit-business flow (Requirements 4, 11.3).
 *
 * A controlled Radix Dialog prefilled from the business. It mirrors
 * {@link AddBusinessDialog}'s fields and validation: entity type must remain an
 * explicit selection (Req 4.3), legal name stays required (Req 4.2), and the EIN
 * hint is non-blocking (Req 4.5). Saves via `updateBusiness`
 * (`PUT /businesses/{id}`); server-side 400 validation errors carry the
 * offending `field`, rendered adjacent to that input.
 */
export function EditBusinessDialog({
  business,
  open,
  onOpenChange,
  onUpdated,
  onCloseAutoFocus,
  update = updateBusiness,
}: EditBusinessDialogProps) {
  const [fields, setFields] = useState<BusinessFormState>(() =>
    formStateFromBusiness(business),
  );
  const [errors, setErrors] = useState<BusinessFieldErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [attempt, setAttempt] = useState(0);

  function resetToBusiness() {
    setFields(formStateFromBusiness(business));
    setErrors({});
    setSubmitting(false);
  }

  function closeNow() {
    resetToBusiness();
    onOpenChange(false);
  }

  const dirty = isDirty({ ...formStateFromBusiness(business) }, { ...fields });
  const guard = useDiscardGuard({ dirty, onClose: closeNow });

  useFocusFirstInvalid({ errors, order: FIELD_ORDER, idFor, attempt });

  const summaryItems: ErrorSummaryItem[] = [
    ...orderedErrors(errors, FIELD_ORDER),
    ...(errors.form ? [{ message: errors.form }] : []),
  ];

  function updateField<K extends keyof BusinessFormState>(
    key: K,
    value: BusinessFormState[K],
  ) {
    setFields((prev) => ({ ...prev, [key]: value }));
  }

  function validate(): BusinessFieldErrors {
    const next: BusinessFieldErrors = {};
    if (!fields.legalName.trim()) next.legal_name = "Legal name is required.";
    if (!fields.entityType) next.entity_type = "Select an entity type.";
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
      const updated = await update(
        business.id,
        buildBusinessInput({
          legalName: fields.legalName,
          entityType: fields.entityType,
          ein: fields.ein,
          formationState: fields.formationState,
          formationDate: fields.formationDate,
          businessAddress: fields.businessAddress,
          taxYearEnd: joinTaxYearEnd(fields.taxYearEndMonth, fields.taxYearEndDay),
          note: fields.note,
        }),
      );
      onUpdated(updated);
      closeNow();
    } catch (err) {
      setSubmitting(false);
      if (err instanceof ApiError && err.status === 400) {
        setErrors(fieldErrorsFromBody(err.body as { field?: string; message?: string } | null));
        setAttempt((n) => n + 1);
        return;
      }
      setErrors({
        form:
          err instanceof ApiError
            ? err.message
            : "Something went wrong while saving the business.",
      });
    }
  }

  return (
    <RecordModal
      open={open}
      onOpenChange={(next) => {
        if (next) onOpenChange(true);
        else guard.requestClose();
      }}
      title="Edit business"
      description="Update the business's legal details. Legal name and entity type are required."
      dismissible={!submitting}
      discard={guard.discard}
      onCloseAutoFocus={onCloseAutoFocus}
    >
      <form className="space-y-4" onSubmit={handleSubmit} noValidate>
        <ErrorSummary
          items={summaryItems}
          idFor={idFor}
          headingId={`${ID_PREFIX}-error-summary`}
        />

        <BusinessFormFields
          idPrefix={ID_PREFIX}
          fields={fields}
          errors={errors}
          onChange={updateField}
        />

        <ModalFormActions>
          <Button type="button" variant="secondary" onClick={guard.requestClose}>
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
