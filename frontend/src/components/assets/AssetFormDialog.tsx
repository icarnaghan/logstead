import { RecordModal, type UseRecordModalResult } from "../ui";
import type { DepreciableAsset } from "../../api/assets";
import { AssetForm, type AssetFormValues } from "./AssetForm";
import type { FieldErrors } from "./assetErrors";

/** Add/edit asset modal wrapping {@link AssetForm}. */
export function AssetFormDialog({
  modal,
  editing,
  submitting,
  formError,
  fieldErrors,
  onSubmit,
}: {
  modal: UseRecordModalResult<DepreciableAsset>;
  editing: DepreciableAsset | null;
  submitting: boolean;
  formError: string | null;
  fieldErrors: FieldErrors;
  onSubmit: (values: AssetFormValues) => Promise<void>;
}) {
  return (
    <RecordModal
      open={modal.open}
      onOpenChange={(next) => {
        if (!next) modal.requestClose();
      }}
      discard={modal.discard}
      title={editing ? "Edit asset" : "Add asset"}
      description={
        editing
          ? "Update this depreciable asset's details."
          : "Enter the details of a depreciable asset."
      }
      dismissible={!submitting}
      onCloseAutoFocus={modal.handleCloseAutoFocus}
    >
      {formError && (
        <p role="alert" className="mb-3 text-sm text-danger">
          {formError}
        </p>
      )}
      <AssetForm
        key={editing?.id ?? "new"}
        asset={editing ?? undefined}
        fieldErrors={fieldErrors}
        submitting={submitting}
        onSubmit={onSubmit}
        onCancel={modal.requestClose}
        onDirtyChange={modal.setDirty}
      />
    </RecordModal>
  );
}
