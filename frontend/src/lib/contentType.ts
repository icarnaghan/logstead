/**
 * Content-type resolution for uploads. Browsers sometimes report an empty
 * `File.type` (e.g. HEIC on desktop browsers), so fall back to the extension.
 * Only types in the backend allow-lists (`adapters/s3_files.py`) are inferred.
 */
const EXTENSION_TYPES: Readonly<Record<string, string>> = {
  pdf: "application/pdf",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
  heic: "image/heic",
  heif: "image/heif",
};

/** Content type for a file name's extension, or "" when unknown. */
export function contentTypeFromFilename(filename: string): string {
  const dot = filename.lastIndexOf(".");
  if (dot < 0) return "";
  return EXTENSION_TYPES[filename.slice(dot + 1).toLowerCase()] ?? "";
}

/**
 * The file's content type (browser-reported, else inferred from the
 * extension) when it is in `allowed`; otherwise `null`.
 */
export function resolveContentType(
  file: Pick<File, "name" | "type">,
  allowed: readonly string[],
): string | null {
  const type = (file.type || contentTypeFromFilename(file.name))
    .trim()
    .toLowerCase();
  return allowed.includes(type) ? type : null;
}
