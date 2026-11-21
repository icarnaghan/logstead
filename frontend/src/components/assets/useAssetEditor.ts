import { useState } from "react";
import { useToast, type UseRecordModalResult } from "../ui";
import type { DepreciableAsset } from "../../api/assets";
import type { AssetFormValues } from "./AssetForm";
import type { AssetsApi } from "./assetsApi";
import { toFieldErrors, type FieldErrors } from "./assetErrors";

/** Add/edit asset submit flow: field + form errors, submit, modal open/close. */
export function useAssetEditor({
  api,
  propertyId,
  modal,
  expandedId,
  loadSchedule,
  reload,
}: {
  api: AssetsApi;
  propertyId: string;
  modal: UseRecordModalResult<DepreciableAsset>;
  expandedId: string | null;
  loadSchedule: (assetId: string) => Promise<void>;
  reload: () => Promise<unknown>;
}) {
  const { notify } = useToast();
  const editing = modal.editing;
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);

  function openAdd() {
    setFieldErrors({});
    setFormError(null);
    modal.openAdd();
  }

  function openEdit(asset: DepreciableAsset) {
    setFieldErrors({});
    setFormError(null);
    modal.openEdit(asset);
  }

  function closeModal() {
    setFieldErrors({});
    setFormError(null);
    modal.close();
  }

  async function handleSubmit(values: AssetFormValues) {
    setSubmitting(true);
    setFieldErrors({});
    setFormError(null);
    try {
      const wasEditing = editing !== null;
      if (editing) {
        await api.updateAsset(propertyId, editing.id, values);
      } else {
        await api.createAsset(propertyId, values);
      }
      closeModal();
      // If the edited asset's schedule was open, refresh it to reflect changes.
      if (editing && expandedId === editing.id) {
        void loadSchedule(editing.id);
      }
      await reload();
      notify({
        variant: "success",
        title: wasEditing ? "Asset updated" : "Asset added",
      });
    } catch (error) {
      const { fieldErrors: fe, message } = toFieldErrors(error);
      setFieldErrors(fe);
      // 400 field errors surface on the fields; a non-field failure shows a
      // form-level message and also toasts.
      if (Object.keys(fe).length === 0) {
        setFormError(message);
        notify({ variant: "error", title: "Could not save the asset" });
      }
    } finally {
      setSubmitting(false);
    }
  }

  return {
    editing,
    submitting,
    fieldErrors,
    formError,
    openAdd,
    openEdit,
    handleSubmit,
  };
}
