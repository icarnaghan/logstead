// Dev-only: generates the static brand assets in frontend/public/.
// Run with: node scripts/generate-brand-icons.mjs (not part of `npm run build`).
// Inputs: src/assets/brand/logo.svg and logo-mark.svg. Outputs are committed.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Resvg } from "@resvg/resvg-js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = (name) => readFileSync(join(root, "src/assets/brand", name), "utf8");
const out = (name) => join(root, "public", name);

const WORDMARK_COLOR = "#0F172A";
const TEAL = "#0F766E";

mkdirSync(join(root, "public"), { recursive: true });

// Public copies: currentColor inside an <img> resolves to black, so bake colors in.
const logo = src("logo.svg").replaceAll("currentColor", WORDMARK_COLOR);
const mark = src("logo-mark.svg").replaceAll("currentColor", WORDMARK_COLOR);
writeFileSync(out("logo.svg"), logo);
writeFileSync(out("logo-mark.svg"), mark);

// Square favicon: the mark on its 140x140 viewBox, no fixed size so it scales.
const favicon = mark
  .replace(/ width="140" height="140"/, "")
  .replace(/ role="img" aria-label="Logstead"/, "");
writeFileSync(out("favicon.svg"), favicon);

// Monogram fallback: letter L in teal on a rounded square.
const monogram = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#F0FDFA" />
  <path d="M22 14 L22 50 L46 50" fill="none" stroke="${TEAL}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round" />
</svg>
`;
writeFileSync(out("favicon-monogram.svg"), monogram);

const render = (svg, width) =>
  new Resvg(svg, { fitTo: { mode: "width", value: width } }).render().asPng();

// favicon-32.png
writeFileSync(out("favicon-32.png"), render(favicon, 32));

// apple-touch-icon.png: 180x180, white background, mark about 64% of the width.
const markSize = Math.round(180 * 0.64);
const offset = (180 - markSize) / 2;
const inner = favicon.replace(
  "<svg ",
  `<svg x="${offset}" y="${offset}" width="${markSize}" height="${markSize}" `,
);
const apple = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 180" width="180" height="180"><rect width="180" height="180" fill="#FFFFFF" />${inner}</svg>`;
writeFileSync(out("apple-touch-icon.png"), render(apple, 180));

console.log("Brand icons written to public/");
