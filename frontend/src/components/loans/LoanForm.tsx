import { useId, useMemo, useState, type FormEvent } from "react";
import type { Loan, LoanInput } from "../../api/loans";
import { projectLoan } from "../../lib/amortization";
import { useDirtyReporter } from "../../lib/dirty";
import { useDismissibleErrors } from "../../lib/useDismissibleErrors";
import { Button, ErrorSummary, DateInput, FormField, Input, MoneyInput, useFocusFirstInvalid, ModalFormActions } from "../ui";
import { orderedErrors, type ErrorSummaryItem } from "../../lib/formErrors";
import {
  emptyLoanForm,
  toLoanInput,
  validateLoanForm,
  type LoanFormErrors,
  type LoanFormField,
  type LoanFormValues,
} from "./loanFormModel";

interface LoanFormProps {
  /** When present, the form is in edit mode and pre-populates from this loan. */
  loan?: Loan;
  /**
   * Server-side errors (from a 400 response) keyed by form field, plus an
   * optional form-level `form` message. Shown alongside client-side errors.
   */
  serverErrors?: LoanFormErrors;
  /** Disables inputs while a submit is in flight. */
  submitting?: boolean;
  onSubmit: (input: LoanInput) => void;
  onCancel?: () => void;
  /** Reports whether the entered values differ from the initial values. */
  onDirtyChange?: (dirty: boolean) => void;
}

function valuesFromLoan(loan: Loan | undefined): LoanFormValues {
  if (!loan) return emptyLoanForm();
  return {
    description: loan.description,
    annualInterestRate: loan.annual_interest_rate,
    monthlyPayment: loan.monthly_payment,
    anchorBalance: loan.anchor_balance,
    anchorDate: loan.anchor_date,
    extraPrincipal: loan.extra_principal,
    payoffDate: loan.payoff_date ?? "",
    originalPrincipal: loan.original_principal ?? "",
    closingDate: loan.closing_date ?? "",
    includeInReport: loan.include_in_report,
  };
}

interface FieldSpec {
  field: LoanFormField;
  label: string;
  type: "text" | "date" | "money";
  inputMode?: "decimal" | "numeric";
  /** True when the shared anchor help text describes this field. */
  anchorHelp?: boolean;
}

const FIELDS: FieldSpec[] = [
  { field: "description", label: "Description", type: "text" },
  {
    field: "annualInterestRate",
    label: "Annual interest rate (%)",
    type: "text",
    inputMode: "decimal",
  },
  {
    field: "monthlyPayment",
    label: "Monthly payment (principal and interest)",
    type: "money",
  },
  {
    field: "anchorBalance",
    label: "Anchor balance",
    type: "money",
    anchorHelp: true,
  },
  { field: "anchorDate", label: "Anchor date", type: "date", anchorHelp: true },
  {
    field: "extraPrincipal",
    label: "Extra principal per month (optional)",
    type: "money",
  },
  { field: "payoffDate", label: "Payoff date (optional)", type: "date" },
  {
    field: "originalPrincipal",
    label: "Original principal (optional)",
    type: "money",
  },
  { field: "closingDate", label: "Closing date (optional)", type: "date" },
];

const FIELD_ORDER = FIELDS.map((f) => f.field);

const ANCHOR_HELP =
  "The anchor balance is the balance after the payment made on the anchor date. The first projected payment is one month later.";

/**
 * Create / edit form for a Loan (Requirements 10.1-10.8, 11.9).
 *
 * All values are held as strings exactly as typed. The Loan_Preview is
 * derived in a `useMemo` from `projectLoan`, so it updates synchronously on
 * each change and disappears (never goes stale) when the projection is null.
 */
export function LoanForm({
  loan,
  serverErrors,
  submitting = false,
  onSubmit,
  onCancel,
  onDirtyChange,
}: LoanFormProps) {
  const baseId = useId();
  const [initialValues] = useState<LoanFormValues>(() => valuesFromLoan(loan));
  const [values, setValues] = useState<LoanFormValues>(initialValues);
  useDirtyReporter({ ...initialValues }, { ...values }, onDirtyChange);
  const [clientErrors, setClientErrors] = useState<LoanFormErrors>({});
  const { errors: visibleServerErrors, dismiss } =
    useDismissibleErrors<LoanFormField | "form">(serverErrors);

  const {
    anchorBalance,
    annualInterestRate,
    monthlyPayment,
    extraPrincipal,
    anchorDate,
    payoffDate,
  } = values;
  const preview = useMemo(
    () =>
      projectLoan({
        anchorBalance,
        annualInterestRate,
        monthlyPayment,
        extraPrincipal,
        anchorDate,
        payoffDate,
      }),
    [
      anchorBalance,
      annualInterestRate,
      monthlyPayment,
      extraPrincipal,
      anchorDate,
      payoffDate,
    ],
  );

  const errors: LoanFormErrors = { ...visibleServerErrors, ...clientErrors };

  // Focus counter: bumped on failed client validation and on new server
  // field errors (store-previous-prop pattern, no effect).
  const [attempt, setAttempt] = useState(0);
  const [prevServerErrors, setPrevServerErrors] = useState(serverErrors);
  if (prevServerErrors !== serverErrors) {
    setPrevServerErrors(serverErrors);
    if (orderedErrors(serverErrors ?? {}, FIELD_ORDER).length > 0) {
      setAttempt((n) => n + 1);
    }
  }
  const idFor = (field: string) => `${baseId}-${field}`;
  useFocusFirstInvalid({ errors, order: FIELD_ORDER, idFor, attempt });
  const summaryItems: ErrorSummaryItem[] = [
    ...orderedErrors(errors, FIELD_ORDER),
    ...(errors.form ? [{ message: errors.form }] : []),
  ];

  function setField(field: LoanFormField, value: string) {
    setValues((prev) => ({ ...prev, [field]: value }));
    // Editing a field hides its server error; the `form` key is never dismissed.
    dismiss(field);
    // Clear a stale message for the field being edited.
    setClientErrors((prev) => {
      if (!prev[field]) return prev;
      const next = { ...prev };
      delete next[field];
      return next;
    });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = validateLoanForm(values);
    setClientErrors(found);
    if (Object.keys(found).length > 0) {
      setAttempt((n) => n + 1);
      return;
    }
    onSubmit(toLoanInput(values));
  }

  const previewId = `${baseId}-preview`;
  const anchorHelpId = `${baseId}-anchor-help`;
  const formErrorId = `${baseId}-form-error`;

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      className="space-y-4"
    >
      <ErrorSummary
        items={summaryItems}
        idFor={idFor}
        headingId={formErrorId}
      />

      {FIELDS.map(({ field, label, type, inputMode, anchorHelp }) => {
        const error = errors[field];
        return (
          <FormField
            key={field}
            id={`${baseId}-${field}`}
            label={label}
            error={error}
          >
            {(control) => {
              const describedBy =
                [control["aria-describedby"], anchorHelp ? anchorHelpId : null]
                  .filter(Boolean)
                  .join(" ") || undefined;
              if (type === "money") {
                return (
                  <MoneyInput
                    {...control}
                    name={field}
                    value={values[field]}
                    onValueChange={(v) => setField(field, v)}
                    disabled={submitting}
                    aria-describedby={describedBy}
                    className="block w-full"
                  />
                );
              }
              if (type === "date") {
                return (
                  <DateInput
                    {...control}
                    name={field}
                    value={values[field]}
                    onValueChange={(v) => setField(field, v)}
                    disabled={submitting}
                    aria-describedby={describedBy}
                    className="block w-full"
                  />
                );
              }
              return (
                <Input
                  {...control}
                  name={field}
                  type="text"
                  inputMode={inputMode}
                  value={values[field]}
                  onChange={(e) => setField(field, e.target.value)}
                  disabled={submitting}
                  aria-describedby={describedBy}
                  className="block w-full"
                />
              );
            }}
          </FormField>
        );
      })}

      <p id={anchorHelpId} className="text-sm text-fg-subtle">
        {ANCHOR_HELP}
      </p>

      {preview !== null && (
        <p id={previewId} data-testid="loan-preview" className="text-sm text-fg">
          Remaining payments: <strong>{preview.remainingPayments}</strong>
          {preview.projectedPayoffDate !== null ? (
            <>
              {" "}
              · Projected payoff date:{" "}
              <strong>{preview.projectedPayoffDate}</strong>
            </>
          ) : preview.payoffBalance !== null ? (
            <>
              {" "}
              · Payoff balance: <strong>${preview.payoffBalance}</strong>
            </>
          ) : null}
        </p>
      )}

      <div className="flex items-center gap-2">
        <input
          id={`${baseId}-includeInReport`}
          name="includeInReport"
          type="checkbox"
          checked={values.includeInReport}
          onChange={(e) =>
            setValues((prev) => ({
              ...prev,
              includeInReport: e.target.checked,
            }))
          }
          disabled={submitting}
          className="h-4 w-4"
        />
        <label
          htmlFor={`${baseId}-includeInReport`}
          className="text-sm font-medium text-fg-muted"
        >
          Include in report
        </label>
      </div>

      <ModalFormActions>
        <Button type="submit" variant="primary" size="sm" disabled={submitting}>
          {loan ? "Save changes" : "Add loan"}
        </Button>
        {onCancel && (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={onCancel}
            disabled={submitting}
          >
            Cancel
          </Button>
        )}
      </ModalFormActions>
    </form>
  );
}
