import { useContext } from "react";
import { ToastContext, type ToastContextValue } from "./ToastProvider";

/**
 * Access the toast API (`{ notify }`) from anywhere inside `ToastProvider`
 * (design: "Toast + ToastProvider", Req 5). Throws a clear error when called
 * outside the provider so misuse fails loudly during development.
 */
export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (context === undefined) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return context;
}
