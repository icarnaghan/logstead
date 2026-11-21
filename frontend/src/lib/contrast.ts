/**
 * WCAG 2.x contrast helpers (pure). Used by the token contrast test to check
 * the Semantic_Token pairs in `index.css` in both themes (Requirements 17, 25).
 */

export type Rgb = readonly [number, number, number];

export interface TokenPair {
  fg: string;
  bg: string;
  min: 3 | 4.5;
  usage: string;
}

/** Parses space-separated channels ("15 118 110") into [r, g, b]. */
export function parseRgbChannels(value: string): [number, number, number] {
  const parts = value.trim().split(/\s+/);
  if (parts.length !== 3) {
    throw new Error(`Expected 3 RGB channels, got "${value}"`);
  }
  const nums = parts.map((p) => Number(p));
  if (nums.some((n) => !Number.isFinite(n) || n < 0 || n > 255)) {
    throw new Error(`Invalid RGB channels "${value}"`);
  }
  return [nums[0], nums[1], nums[2]];
}

/** Parses "#RRGGBB" or "#RGB" into [r, g, b]. */
export function parseHex(hex: string): [number, number, number] {
  let h = hex.trim().replace(/^#/, '');
  if (h.length === 3) {
    h = h
      .split('')
      .map((c) => c + c)
      .join('');
  }
  if (!/^[0-9a-fA-F]{6}$/.test(h)) {
    throw new Error(`Invalid hex color "${hex}"`);
  }
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

/** WCAG 2.x relative luminance of an sRGB color with 0-255 channels. */
export function relativeLuminance(rgb: Rgb): number {
  const [r, g, b] = rgb.map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG 2.x contrast ratio, from 1 to 21. Argument order does not matter. */
export function contrastRatio(a: readonly number[], b: readonly number[]): number {
  const la = relativeLuminance(a as Rgb);
  const lb = relativeLuminance(b as Rgb);
  const hi = Math.max(la, lb);
  const lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

function parseBlock(body: string): Record<string, string> {
  const out: Record<string, string> = {};
  const re = /--color-([a-z0-9-]+)\s*:\s*([^;]+);/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(body)) !== null) {
    out[m[1]] = m[2].trim();
  }
  return out;
}

function findBlock(css: string, selector: RegExp): string {
  const m = selector.exec(css);
  if (!m) return '';
  const start = css.indexOf('{', m.index + m[0].length - 1);
  if (start < 0) return '';
  let depth = 0;
  for (let i = start; i < css.length; i++) {
    if (css[i] === '{') depth++;
    else if (css[i] === '}') {
      depth--;
      if (depth === 0) return css.slice(start + 1, i);
    }
  }
  return '';
}

/**
 * Parses the `:root` and `.dark` blocks of a stylesheet and returns the
 * `--color-*` variables of each, keyed without the `--color-` prefix.
 */
export function readTokens(css: string): {
  light: Record<string, string>;
  dark: Record<string, string>;
} {
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, '');
  return {
    light: parseBlock(findBlock(stripped, /(^|[\s}]):root\s*\{/)),
    dark: parseBlock(findBlock(stripped, /(^|[\s}])\.dark\s*\{/)),
  };
}

/** Requirement 25.1 pairs plus the extra rows from the design's contrast table. */
export const TOKEN_PAIRS: TokenPair[] = [
  { fg: 'fg', bg: 'canvas', min: 4.5, usage: 'body text on page' },
  { fg: 'fg', bg: 'surface', min: 4.5, usage: 'body text on cards' },
  { fg: 'fg-muted', bg: 'canvas', min: 4.5, usage: 'secondary text on page' },
  { fg: 'fg-muted', bg: 'surface', min: 4.5, usage: 'secondary text on cards' },
  { fg: 'fg-muted', bg: 'surface-muted', min: 4.5, usage: 'secondary text on hover rows' },
  { fg: 'fg-subtle', bg: 'canvas', min: 4.5, usage: 'tertiary text on page' },
  { fg: 'fg-subtle', bg: 'surface', min: 4.5, usage: 'tertiary text on cards' },
  { fg: 'fg-subtle', bg: 'surface-muted', min: 4.5, usage: 'tertiary text on hover rows' },
  { fg: 'accent-fg', bg: 'accent', min: 4.5, usage: 'primary button label' },
  { fg: 'accent-fg', bg: 'accent-hover', min: 4.5, usage: 'primary button label on hover' },
  { fg: 'accent', bg: 'canvas', min: 4.5, usage: 'accent text on page' },
  { fg: 'accent', bg: 'surface', min: 4.5, usage: 'accent text on cards' },
  { fg: 'accent', bg: 'accent-subtle', min: 4.5, usage: 'active nav item, Badge' },
  { fg: 'accent', bg: 'canvas', min: 3, usage: 'focus ring and boundary on page' },
  { fg: 'accent', bg: 'surface', min: 3, usage: 'focus ring and boundary on cards' },
  { fg: 'success', bg: 'success-subtle', min: 4.5, usage: 'success message' },
  { fg: 'danger', bg: 'danger-subtle', min: 4.5, usage: 'error message' },
  { fg: 'warning', bg: 'warning-subtle', min: 4.5, usage: 'warning message' },
  { fg: 'border-strong', bg: 'canvas', min: 3, usage: 'control boundary on page' },
  { fg: 'border-strong', bg: 'surface', min: 3, usage: 'control boundary on cards' },
  { fg: 'brand-tagline', bg: 'canvas', min: 4.5, usage: 'logo tagline on page' },
  { fg: 'brand-tagline', bg: 'surface', min: 4.5, usage: 'logo tagline on cards' },
  { fg: 'brand-orange', bg: 'canvas', min: 3, usage: 'decorative graphic on page' },
  { fg: 'brand-orange', bg: 'surface', min: 3, usage: 'decorative graphic on cards' },
];
