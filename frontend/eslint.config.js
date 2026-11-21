import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import jsxA11y from 'eslint-plugin-jsx-a11y';

/**
 * Palette rules (Requirements 17.1, 17.3, 17.4, 25.3): components use Semantic
 * Tokens only. Enforced on string and template literals, so comments never
 * trip them. esquery regex literals cannot contain a slash, hence \\x2f.
 */
const COLOR_NAMES =
  'slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|gold|white|black';
const PALETTE_PREFIXES =
  'bg|text|border|ring|from|to|via|fill|stroke|outline|divide|placeholder|decoration|accent|caret|shadow';
const paletteRules = [
  {
    // Raw Tailwind palette utilities (bg-indigo-500, text-gold, bg-white, ...).
    re: `(?<![\\w-])(?:[a-z-]+:)*(?:${PALETTE_PREFIXES})-(?:${COLOR_NAMES})(?:-\\d+)?(?:\\x2f\\d+)?(?![\\w-])`,
    message:
      'Use Semantic_Tokens (bg-surface, text-fg, ...), not raw Tailwind palette colors.',
  },
  {
    re: '#[0-9a-fA-F]{3,8}\\b',
    message: 'No hard-coded hex colors; use a Semantic_Token.',
  },
  {
    re: '\\b(?:rgba?|hsla?)\\((?!\\s*var\\()',
    message:
      'No literal rgb()/hsl() colors; only rgb(var(--color-...)) token references.',
  },
  {
    re: 'text-brand-orange',
    message: 'text-brand-orange is not allowed; it fails text contrast.',
  },
  {
    re: '(?<![\\w-])(?:[a-z-]+:)*text-[a-z-]*(?:amber|gold)[a-z-]*',
    message: 'Amber and gold are never used for text.',
  },
].flatMap(({ re, message }) => [
  { selector: `Literal[value=/${re}/]`, message },
  { selector: `TemplateElement[value.raw=/${re}/]`, message },
]);
paletteRules.push(
  ...['Literal[value', 'TemplateElement[value.raw'].map((head) => ({
    selector: `${head}=/\\btext-fg-subtle\\b/]${head}=/\\bbg-accent-subtle\\b/]`,
    message: 'text-fg-subtle must not be combined with bg-accent-subtle (contrast).',
  })),
);

/**
 * Page conformance (Requirements 4.5, 4.6, 5.8): the shared PageHeader /
 * PropertySection owns the single page heading, so pages render no <h1>, and
 * no heading element carries text-2xl or larger (metric figures in <p> may).
 */
const pageRules = [
  {
    selector: "JSXOpeningElement[name.name='h1']",
    message:
      'Pages must not render <h1>; PageHeader / PropertySection owns the page heading.',
  },
  {
    selector:
      "JSXOpeningElement[name.name=/^h[1-6]$/] JSXAttribute[name.name='className'] Literal[value=/text-(2xl|3xl|4xl)/]",
    message: 'Heading elements must not use text-2xl or larger on pages.',
  },
  {
    selector:
      "JSXOpeningElement[name.name=/^h[1-6]$/] JSXAttribute[name.name='className'] TemplateElement[value.raw=/text-(2xl|3xl|4xl)/]",
    message: 'Heading elements must not use text-2xl or larger on pages.',
  },
];

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'coverage', '.aws-sam', 'scripts/*.mjs', 'playwright-report', 'test-results'] },
  js.configs.recommended,
  tseslint.configs.recommended,
  jsxA11y.flatConfigs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: { globals: { ...globals.browser } },
    plugins: { react, 'react-hooks': reactHooks },
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'none' },
      ],
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // Security rules
      'no-eval': 'error',
      'no-implied-eval': 'error',
      'no-new-func': 'error',
      'react/no-danger': 'error',
      'react/jsx-no-target-blank': 'error',
    },
  },
  {
    // Documented exceptions: tests, test helpers, and the brand logo/splash,
    // which legitimately carry brand hex values and gradients.
    files: ['src/**/*.tsx'],
    ignores: ['src/**/*.test.tsx', 'src/test/**', 'src/components/brand/**'],
    rules: { 'no-restricted-syntax': ['error', ...paletteRules] },
  },
  {
    // Overrides replace (not merge) rule options, so repeat the palette rules.
    files: ['src/pages/*.tsx'],
    ignores: ['src/**/*.test.tsx'],
    rules: { 'no-restricted-syntax': ['error', ...paletteRules, ...pageRules] },
  },
  {
    files: ['public/**/*.js'],
    languageOptions: { globals: { ...globals.browser } },
  },
  {
    files: ['*.config.{js,ts}', 'vite.config.ts', 'e2e/**/*.ts'],
    languageOptions: { globals: { ...globals.node } },
  },
);
