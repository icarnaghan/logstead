import { readdirSync, readFileSync } from "node:fs";
import { basename, join } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

/**
 * Source scan: the UI must hold no threshold number (Requirements 3.5, 22.12).
 * Thresholds live in the backend Checklist_Config; the UI only shows the
 * Reason text and `details` the API returns. Numeric literals in non-string
 * code of the feature files may therefore be only 0, 1 (and -1, which is a
 * unary minus on 1).
 */

const HERE = __dirname;
const SRC = join(HERE, "..", "..");
const ALLOWED = new Set([0, 1]);

/**
 * Literals that are not thresholds: an SVG stroke width, a path-segment index
 * and a skeleton column count. Keyed by file name and literal text so a new
 * number anywhere else still fails the scan.
 */
const NON_THRESHOLD = new Set([
  "YearEndStatusBadge.tsx:1.75",
  "yearEndText.ts:2",
  "YearEndChecklistPage.tsx:3",
]);

function featureFiles(): string[] {
  const inFolder = readdirSync(HERE)
    .filter((n) => /\.tsx?$/.test(n) && !/\.test\.tsx?$/.test(n))
    .map((n) => join(HERE, n));
  return [
    ...inFolder,
    join(SRC, "pages", "YearEndChecklistPage.tsx"),
    join(SRC, "api", "yearEndChecklist.ts"),
  ];
}

function offendingLiterals(file: string): string[] {
  const text = readFileSync(file, "utf8");
  const kind = file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  const found: string[] = [];
  const visit = (node: ts.Node): void => {
    if (
      ts.isNumericLiteral(node) &&
      !ALLOWED.has(Number(node.text)) &&
      !NON_THRESHOLD.has(`${basename(file)}:${node.text}`)
    ) {
      const { line } = source.getLineAndCharacterOfPosition(node.getStart(source));
      found.push(`${file}:${line + 1} ${node.getText(source)}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

describe("year-end checklist source scan", () => {
  const files = featureFiles();

  it("scans the new feature files", () => {
    expect(files.length).toBeGreaterThan(5);
  });

  it("uses no numeric literal other than 0, 1 and -1 in non-string code", () => {
    const offenders = files.flatMap(offendingLiterals);
    expect(offenders).toEqual([]);
  });

  it("detects a hard-coded threshold in sample code", () => {
    const sample = ts.createSourceFile(
      "x.ts",
      'const a = 250; const b = -1; const c = "2500"; const d = `${0}`;',
      ts.ScriptTarget.Latest,
      true,
    );
    const bad: string[] = [];
    const visit = (n: ts.Node): void => {
      if (ts.isNumericLiteral(n) && !ALLOWED.has(Number(n.text))) bad.push(n.text);
      ts.forEachChild(n, visit);
    };
    visit(sample);
    expect(bad).toEqual(["250"]);
  });
});
