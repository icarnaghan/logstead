import clsx, { type ClassValue } from "clsx";

/** Compose conditional class names. Thin wrapper so we can swap the impl later. */
export function cn(...inputs: ClassValue[]): string {
  return clsx(inputs);
}

export type { ClassValue };
