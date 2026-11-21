import { useState } from "react";
import { Button, ConfirmDialog } from "../ui";
import { deleteBusiness, ApiError, type Business } from "../../api/businesses";

interface DeleteBusinessConfirmProps {
  /** The business to delete (its id drives the call, its name the prompt). */
  business: Pick<Business, "id" | "legal_name">;
  /** Called with the deleted business id after a successful delete. */
  onDeleted: (id: string) => void;
  /** Test seam: delete call. Defaults to the real `deleteBusiness`. */
  del?: (id: string) => Promise<void>;
}

/**
 * Delete-business flow with guarded-delete 409 surfacing (Requirements 5.2,
 * 11.3, 11.6).
 *
 * A trigger button opens the shared {@link ConfirmDialog} naming the business.
 * On confirm it calls `deleteBusiness` (`DELETE /businesses/{id}`):
 *
 *  - Success closes the dialog and calls `onDeleted(id)` so the list can drop
 *    the row.
 *  - A **409 conflict** means the backend's delete-guard found linked
 *    properties (Req 5.2). We surface the backend's own conflict message inline
 *    in a `role="alert"` region **and keep the dialog open** so the user can go
 *    unlink/reassign the properties before trying again.
 *  - Any other failure surfaces a generic message, also keeping the dialog open.
 *
 * `ConfirmDialog` is `open`/`onOpenChange`-controlled and has no built-in error
 * slot, so this component owns the `open` state and injects the conflict alert
 * into the dialog's `description` ReactNode.
 */
export function DeleteBusinessConfirm({
  business,
  onDeleted,
  del = deleteBusiness,
}: DeleteBusinessConfirmProps) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    // Reset transient state whenever the dialog closes so a reopen starts clean.
    if (!next) {
      setPending(false);
      setError(null);
    }
  }

  async function handleConfirm() {
    setPending(true);
    setError(null);
    try {
      await del(business.id);
      setPending(false);
      setOpen(false);
      onDeleted(business.id);
    } catch (err) {
      setPending(false);
      if (err instanceof ApiError && err.status === 409) {
        // The delete-guard rejected the delete: show the backend's reassign /
        // unlink-first message and keep the dialog open (Req 5.2, 11.6).
        setError(conflictMessage(err));
        return;
      }
      setError("Something went wrong while deleting the business.");
    }
  }

  return (
    <>
      <Button
        type="button"
        variant="danger"
        onClick={() => handleOpenChange(true)}
      >
        Delete
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={handleOpenChange}
        title="Delete business"
        confirmLabel="Delete"
        pending={pending}
        onConfirm={handleConfirm}
        description={
          <span className="block space-y-3">
            <span className="block">
              Delete <span className="font-medium text-fg">{business.legal_name}</span>?
              This can't be undone.
            </span>
            {error ? (
              <span
                role="alert"
                className="block rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger"
              >
                {error}
              </span>
            ) : null}
          </span>
        }
      />
    </>
  );
}

/**
 * Pull the human-readable conflict message off a 409 {@link ApiError},
 * preferring the parsed body's `message` and falling back to the error's own
 * `message` (which the client already derives from the body when present).
 */
function conflictMessage(err: ApiError): string {
  const body = err.body;
  if (
    body !== null &&
    typeof body === "object" &&
    "message" in body &&
    typeof (body as { message?: unknown }).message === "string" &&
    (body as { message: string }).message.trim() !== ""
  ) {
    return (body as { message: string }).message;
  }
  return err.message;
}
