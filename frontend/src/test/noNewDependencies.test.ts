import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { APP_ROUTES, leafPaths } from "../routes";

/**
 * ui-polish guards: no new npm dependency, only the two documented routes
 * added, and nothing in the sources that the Content-Security-Policy
 * (script-src 'self') would block.
 * Validates: Requirements 28.1, 28.6, 28.8, 28.9, 29.1
 */
const ROOT = join(__dirname, "..", "..");
const SRC = join(ROOT, "src");

const RUNTIME = [
  "@radix-ui/react-dialog",
  "@radix-ui/react-dropdown-menu",
  "@radix-ui/react-navigation-menu",
  "@radix-ui/react-slot",
  "@radix-ui/react-toast",
  "clsx",
  "react",
  "react-dom",
  "react-router-dom",
  "recharts",
];
const DEV = [
  "@axe-core/playwright",
  "@eslint/js",
  "@playwright/test",
  "@resvg/resvg-js",
  "@testing-library/jest-dom",
  "@testing-library/react",
  "@testing-library/user-event",
  "@types/node",
  "@types/react",
  "@types/react-dom",
  "@vitejs/plugin-react",
  "autoprefixer",
  "axe-core",
  "eslint",
  "eslint-plugin-jsx-a11y",
  "eslint-plugin-react",
  "eslint-plugin-react-hooks",
  "fast-check",
  "globals",
  "jsdom",
  "opentype.js",
  "postcss",
  "tailwindcss",
  "typescript",
  "typescript-eslint",
  "vite",
  "vitest",
  "vitest-axe",
];

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      if (name === "test") continue;
      out.push(...sourceFiles(full));
    } else if (/\.(ts|tsx|css)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name)) {
      out.push(full);
    }
  }
  return out;
}

function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
}

describe("no new dependencies", () => {
  const pkg = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8")) as {
    dependencies: Record<string, string>;
    devDependencies: Record<string, string>;
  };

  it("keeps the runtime dependency names unchanged", () => {
    expect(Object.keys(pkg.dependencies).sort()).toEqual([...RUNTIME].sort());
  });

  it("keeps the devDependency names unchanged", () => {
    expect(Object.keys(pkg.devDependencies).sort()).toEqual([...DEV].sort());
  });
});

describe("route table", () => {
  it("has exactly the existing routes plus /search and /activity", () => {
    const expected = [
      "/",
      "/properties",
      "/businesses",
      "/businesses/:businessId",
      "/reports",
      "/carryforward",
      "/accountant-package",
      "/imports/schedule-e",
      "/imports/schedule-e/extract",
      "/properties/:propertyId",
      "/properties/:propertyId/transactions",
      "/properties/:propertyId/repairs",
      "/properties/:propertyId/assets",
      "/properties/:propertyId/loans",
      "/properties/:propertyId/reports",
      "/properties/:propertyId/checklist",
      "/activity",
      "/search",
      "/profile",
      "/*",
    ];
    expect([...leafPaths(APP_ROUTES)].sort()).toEqual([...expected].sort());
  });
});

describe("CSP-safe sources", () => {
  const files = sourceFiles(SRC);
  const scan = (pattern: RegExp): string[] =>
    files.flatMap((file) => {
      const code = stripComments(readFileSync(file, "utf8"));
      return pattern.test(code) ? [relative(ROOT, file)] : [];
    });

  it("finds source files to scan", () => {
    expect(files.length).toBeGreaterThan(50);
  });

  it("uses no dangerouslySetInnerHTML, eval, Function constructor or inline script", () => {
    expect(scan(/dangerouslySetInnerHTML/)).toEqual([]);
    expect(scan(/\beval\s*\(/)).toEqual([]);
    expect(scan(/\bnew\s+Function\s*\(/)).toEqual([]);
    expect(scan(/<script\b/i)).toEqual([]);
    expect(scan(/\bset(Timeout|Interval)\s*\(\s*["'`]/)).toEqual([]);
    expect(scan(/javascript:/i)).toEqual([]);
  });

  it("loads no external URL (only the SVG namespace and the URL-parsing placeholder)", () => {
    const allowed = /^https?:\/\/(www\.w3\.org\/2000\/svg|relative\.invalid)/;
    const offenders = files.flatMap((file) => {
      const code = stripComments(readFileSync(file, "utf8"));
      return (code.match(/https?:\/\/[^\s"'`)]+/g) ?? [])
        .filter((url) => !allowed.test(url))
        .map((url) => `${relative(ROOT, file)}: ${url}`);
    });
    expect(offenders).toEqual([]);
  });

  it("index.html has only external script files", () => {
    const html = readFileSync(join(ROOT, "index.html"), "utf8");
    const tags = html.match(/<script\b[^>]*>/gi) ?? [];
    expect(tags.length).toBeGreaterThan(0);
    for (const tag of tags) expect(tag).toMatch(/\bsrc="\/[^"]+"/);
    expect(html).not.toMatch(/<script\b[^>]*>\s*[^<\s]/i);
    expect(html).not.toMatch(/<style\b/i);
  });
});
