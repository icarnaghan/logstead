import type { PaletteItem } from "./paletteItems";

/** Maximum Search_Tokens kept from a query (matches the server rule). */
export const MAX_TOKENS = 5;

/** NFKC normalization, case folding and whitespace collapse. Idempotent. */
export function normalize(text: string): string {
  let out = text.normalize("NFKC").toLowerCase().normalize("NFKC");
  out = out.replace(/\s+/g, " ").trim();
  return out;
}

/** Split a query into at most 5 non-empty, normalized tokens. */
export function tokenize(query: string): string[] {
  const tokens: string[] = [];
  for (const part of normalize(query).split(" ")) {
    if (part === "") continue;
    const token = normalize(part);
    if (token === "") continue;
    tokens.push(token);
    if (tokens.length === MAX_TOKENS) break;
  }
  return tokens;
}

function compareText(a: string, b: string): number {
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

/**
 * Filter and rank local palette items (Requirements 5.1 to 5.4). Keeps items
 * whose label or keywords contain every token; ranks exact label, then a label
 * word starting with a token, then any other match; ties break by the fixed
 * item order, then label. Returns at most `limit` items.
 */
export function rankLocal(
  items: readonly PaletteItem[],
  query: string,
  limit: number,
): PaletteItem[] {
  const tokens = tokenize(query);
  const normalizedQuery = tokens.join(" ");
  const ranked: { item: PaletteItem; tier: number; order: number; label: string }[] = [];

  items.forEach((item, order) => {
    const label = normalize(item.label);
    const haystack = [label, ...item.keywords.map(normalize)].join(" ");
    if (!tokens.every((token) => haystack.includes(token))) return;
    let tier = 2;
    if (tokens.length > 0 && label === normalizedQuery) {
      tier = 0;
    } else {
      const words = label.split(" ");
      if (tokens.some((token) => words.some((word) => word.startsWith(token)))) {
        tier = 1;
      }
    }
    ranked.push({ item, tier, order, label });
  });

  ranked.sort(
    (a, b) => a.tier - b.tier || a.order - b.order || compareText(a.label, b.label),
  );
  return ranked.slice(0, Math.max(0, limit)).map((entry) => entry.item);
}

/** Move the highlight by one, wrapping at the ends. Returns -1 for an empty list. */
export function moveHighlight(
  index: number,
  length: number,
  direction: "next" | "prev" | 1 | -1,
): number {
  if (length <= 0) return -1;
  const step = direction === "next" || direction === 1 ? 1 : -1;
  return (((index + step) % length) + length) % length;
}
