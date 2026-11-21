const CONTENTS: readonly string[] = [
  "Schedule E reports for each property as PDF, CSV, and JSON, plus a combined report when you pick two or more properties.",
  "A transactions spreadsheet (CSV) listing every transaction of the year.",
  "Your receipts, filed by property and category.",
  "The year-end checklist summary, when it is available.",
  "A README and a manifest listing each file with its checksum.",
];

/** Plain-language list of what the package holds, shown before preparing. */
export function PackageContentsList() {
  return (
    <section aria-labelledby="package-contents-heading">
      <h2 id="package-contents-heading" className="text-sm font-medium text-fg">
        What is in the package
      </h2>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-fg-muted">
        {CONTENTS.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}
