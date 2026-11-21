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
  createBusiness,
  ApiError,
  type Business,
  type BusinessInput,
} from "../../api/businesses";
import { BusinessFormFields, type BusinessFormState } from "./BusinessFormFields";
import {
  DEFAULT_TAX_YEAR_END,
  buildBusinessInput,
  fieldErrorsFromBody,
  joinTaxYearEnd,
  splitTaxYearEnd,
  type BusinessFieldErrors,
} from "./businessForm";

interface AddBusinessDialogProps {
  /** Called with the newly created business so the list can refresh. */
  onCreated: (business: Business) => void;
  /** Test seam: create call. Defaults to the real `createBusiness`. */
  create?: (input: BusinessInput) => Promise<Business>;
  /**
   * Controlled open state. When undefined the dialog is uncontrolled and
   * renders its own "Add business" trigger.
   */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

const FIELD_ORDER = ["legal_name", "entity_type"] as const;
const ID_PREFIX = "add-business";
const FIELD_IDS: Record<(typeof FIELD_ORDER)[number], string> = {
  legal_name: `${ID_PREFIX}-legal-name`,
  entity_type: `${ID_PREFIX}-entity-type`,
};
const idFor = (field: string) =>
  FIELD_IDS[field as keyof typeof FIELD_IDS] ?? `${ID_PREFIX}-${field}`;

function emptyFormState(): BusinessFormState {
  const { month, day } = splitTaxYearEnd(DEFAULT_TAX_YEAR_END);
  return {
    legalName: "",
    entityType: "",
    ein: "",
    formationState: "",
    formationDate: "",
    businessAddress: "",
    taxYearEndMonth: month,
    taxYearEndDay: day,
    note: "",
  };
}

/**
 * Add-business flow (Requirements 1, 11.3).
 *
 * A Radix Dialog holding the business form. The entity type must be chosen
 * explicitly (the `<select>` starts on a non-submittable placeholder, so leaving
 * it unset is a client-side validation error, Req 1.5). The EIN input carries a
 * `NN-NNNNNNN` placeholder hint but is never validated or required (Req 1.6).
 * `formation_state` is a 50-states + DC dropdown, `formation_date` a native date
 * input, and `tax_year_end` a month/day control defaulting to "12-31" (Req 1.3).
 * On submit it posts to `createBusiness`; server-side 400 validation errors
 * carry the offending `field`, rendered adjacent to that input (mirrors
 * {@link AddPropertyDialog}).
 */
export function AddBusinessDialog({
  onCreated,
  create = createBusiness,
  open: openProp,
  onOpenChange,
}: AddBusinessDialogProps) {
  const [internalOpen, setInternalOpen] = useState(false);
  const controlled = openProp !== undefined;
  const open = controlled ? openProp : internalOpen;
  const setOpen = (next: boolean) => {
    if (!controlled) setInternalOpen(next);
    onOpenChange?.(next);
  };
  const [attempt, setAttempt] = useState(0);
  const [fields, setFields] = useState<BusinessFormState>(emptyFormState);
  const [errors, setErrors] = useState<BusinessFieldErrors>({});
  const [submitting, setSubmitting] = useState(false);

  function resetForm() {
    setFields(emptyFormState());
    setErrors({});
    setSubmitting(false);
  }

  function closeNow() {
    resetForm();
    setOpen(false);
  }

  const dirty = isDirty({ ...emptyFormState() }, { ...fields });
  const guard = useDiscardGuard({ dirty, onClose: closeNow });

  useFocusFirstInvalid({
    errors,
    order: FIELD_ORDER,
    idFor,
    attempt,
  });

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
      const business = await create(
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
      onCreated(business);
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
    <>
      {controlled ? null : (
        <Button type="button" variant="primary" onClick={() => setOpen(true)}>
          Add business
        </Button>
      )}
      <RecordModal
        open={open}
        onOpenChange={(next) => {
          if (next) setOpen(true);
          else guard.requestClose();
        }}
        title="Add a business"
        description="Enter the business's legal details. Only the legal name and entity type are required — everything else is optional."
        dismissible={!submitting}
        discard={guard.discard}
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
            <Button
              type="button"
              variant="secondary"
              onClick={guard.requestClose}
            >
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={submitting}>
              {submitting ? "Saving…" : "Save business"}
            </Button>
          </ModalFormActions>
        </form>
      </RecordModal>
    </>
  );
}
