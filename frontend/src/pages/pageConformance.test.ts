import { describe, expect, it } from "vitest";

/**
 * Page conformance source scan (Requirements 4.5, 4.6, 5.8, 14.4-14.8).
 *
 * The "no `<h1` in pages" and "no text-2xl+ on heading elements" rules moved to
 * `no-restricted-syntax` selectors in `eslint.config.js` (they are codebase-wide
 * bans). What remains here stays a source scan on purpose: these are "every
 * page must contain X" checks (PageHeader/PropertySection, document title,
 * useFirstLoad + StateBlock error, allowlisted hand-rolled alerts). A lint rule
 * cannot express "file must contain" or the stale-allowlist check, and a
 * rendered check would need an API fixture for each of the pages.
 *
 * 1. Every page except the Schedule E import tab pages (which render inside
 *    ImportsLayout) uses PageHeader or PropertySection and sets the document
 *    title, either directly via `useDocumentTitle` or through PropertySection.
 * 2. Load errors surface through `StateBlock kind="error"`, not hand-rolled
 *    alert paragraphs (see the allowlist below).
 */
const sources = import.meta.glob("./*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/**
 * Sections extracted out of a page into a feature folder (task 6.3). Only the
 * hand-rolled alert scan covers them; the page-level checks below stay on the
 * route entries in this folder.
 */
const extractedSources = import.meta.glob(
  [
    "../components/property-detail/NotesTile.tsx",
    "../components/assets/AssetFormDialog.tsx",
    "../components/assets/AssetScheduleSection.tsx",
  ],
  { query: "?raw", import: "default", eager: true },
) as Record<string, string>;

const extracted = Object.entries(extractedSources).map(([path, raw]) => ({
  name: path.replace(/^.*\//, "").replace(/\.tsx$/, ""),
  code: stripComments(raw),
}));

// RepairsPage is a thin wrapper that renders ItemizedExpensesPage, which is scanned itself.
const EXEMPT = new Set(["ScheduleEImportPage", "ScheduleEExtractionPage", "RepairsPage"]);

function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

const pages = Object.entries(sources)
  // Skip tests and stray Finder duplicates ("Name 2.tsx") whose names contain a space.
  .filter(([path]) => !/\.test\.tsx$/.test(path) && !/\s/.test(path))
  .map(([path, raw]) => ({
    name: path.replace(/^\.\//, "").replace(/\.tsx$/, ""),
    code: stripComments(raw),
  }));

/**
 * Load-error conformance (Requirements 14.4, 14.6, 14.7, 14.8): list/report
 * loads surface failures through `StateBlock kind="error"` driven by
 * `useFirstLoad`, never a hand-rolled `<p role="alert" class="text-danger">`.
 *
 * Hand-rolled alert paragraphs that remain are keyed `Page:{expression}` where
 * the expression is the first `{...}` rendered inside the paragraph. Each
 * entry is a documented exception.
 */
const HAND_ROLLED_ALERT_ALLOWLIST: Record<string, string> = {
  // Not load errors: results of user actions, announced inline.
  "NotesTile:error": "Notes tile save failure, not a load.",
  "TransactionsPage:deleteError": "Delete failure, not a load.",
  "LoansPage:deleteError": "Delete failure, not a load.",
  "AssetScheduleSection:overrideGeneralError":
    "Depreciation override save failure.",
  "AssetFormDialog:formError": "Add/edit asset form submit failure.",
};

function handRolledAlerts(code: string): string[] {
  const keys: string[] = [];
  const re = /<p\b[^>]*>/g;
  for (let m = re.exec(code); m; m = re.exec(code)) {
    const tag = m[0];
    if (!/role="alert"/.test(tag) || !/text-danger/.test(tag)) continue;
    const rest = code.slice(m.index + tag.length, m.index + tag.length + 200);
    const expr = /\{\s*([\w.]+)\s*\}/.exec(rest);
    keys.push(expr ? expr[1] : "(static)");
  }
  return keys;
}

describe("load-error conformance (source scan)", () => {
  it("every useFirstLoad page renders StateBlock kind=\"error\"", () => {
    for (const { name, code } of pages) {
      if (/\buseFirstLoad\(/.test(code)) {
        expect(code, `${name} should render a StateBlock error`).toMatch(
          /kind="error"/,
        );
      }
    }
  });

  it("rolled-out pages use useFirstLoad", () => {
    const rolledOut = [
      "PropertiesPage",
      "BusinessesPage",
      "BusinessDetailPage",
      "PropertyDetailPage",
      "TransactionsPage",
      "AssetsPage",
      "LoansPage",
      "ReportsPage",
      "CombinedReportsPage",
      "CarryforwardPage",
    ];
    for (const name of rolledOut) {
      const page = pages.find((p) => p.name === name);
      expect(page, `${name} source`).toBeDefined();
      expect(page!.code, `${name} uses useFirstLoad`).toMatch(/\buseFirstLoad\(/);
    }
  });

  it("has no hand-rolled text-danger alert paragraph outside the documented exceptions", () => {
    const unexpected: string[] = [];
    for (const { name, code } of [...pages, ...extracted]) {
      for (const expr of handRolledAlerts(code)) {
        if (!(`${name}:${expr}` in HAND_ROLLED_ALERT_ALLOWLIST)) {
          unexpected.push(`${name}:${expr}`);
        }
      }
    }
    expect(unexpected).toEqual([]);
  });

  it("allowlist has no stale entries", () => {
    const present = new Set<string>();
    for (const { name, code } of [...pages, ...extracted]) {
      for (const expr of handRolledAlerts(code)) present.add(`${name}:${expr}`);
    }
    const stale = Object.keys(HAND_ROLLED_ALERT_ALLOWLIST).filter(
      (k) => !present.has(k),
    );
    expect(stale).toEqual([]);
  });
});

describe("page conformance (source scan)", () => {
  it("finds page sources to scan", () => {
    expect(pages.length).toBeGreaterThan(5);
  });

  describe.each(pages.filter((p) => !EXEMPT.has(p.name)))("$name", ({ code }) => {
    it("uses PageHeader or PropertySection", () => {
      expect(code).toMatch(/\b(PageHeader|PropertySection)\b/);
    });
    it("sets the document title (directly or via PropertySection)", () => {
      expect(code).toMatch(/\b(useDocumentTitle|PropertySection)\b/);
    });
  });
});
