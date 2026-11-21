/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Semantic color tokens backed by CSS variables (see index.css). Each
        // resolves to a different value under the `.dark` class, so components
        // reference intent (surface/fg/accent/...) rather than literal palette
        // colors and get light + dark for free.
        canvas: "rgb(var(--color-canvas) / <alpha-value>)", // app background
        surface: "rgb(var(--color-surface) / <alpha-value>)", // cards/panels
        "surface-muted": "rgb(var(--color-surface-muted) / <alpha-value>)", // subtle fills
        border: "rgb(var(--color-border) / <alpha-value>)",
        "border-strong": "rgb(var(--color-border-strong) / <alpha-value>)", // form control boundaries (3:1)
        "brand-orange": "rgb(var(--color-brand-orange) / <alpha-value>)", // decorative/chart only, never text
        fg: "rgb(var(--color-fg) / <alpha-value>)", // primary text
        "fg-muted": "rgb(var(--color-fg-muted) / <alpha-value>)", // secondary text
        "fg-subtle": "rgb(var(--color-fg-subtle) / <alpha-value>)", // tertiary/placeholder
        accent: "rgb(var(--color-accent) / <alpha-value>)",
        "accent-hover": "rgb(var(--color-accent-hover) / <alpha-value>)",
        "accent-fg": "rgb(var(--color-accent-fg) / <alpha-value>)", // text on accent
        "accent-subtle": "rgb(var(--color-accent-subtle) / <alpha-value>)", // tinted fill
        success: "rgb(var(--color-success) / <alpha-value>)",
        "success-subtle": "rgb(var(--color-success-subtle) / <alpha-value>)",
        danger: "rgb(var(--color-danger) / <alpha-value>)",
        "danger-subtle": "rgb(var(--color-danger-subtle) / <alpha-value>)",
        warning: "rgb(var(--color-warning) / <alpha-value>)",
        "warning-subtle": "rgb(var(--color-warning-subtle) / <alpha-value>)",
      },
      fill: {
        "brand-tagline": "rgb(var(--color-brand-tagline) / <alpha-value>)",
      },
      borderColor: {
        DEFAULT: "rgb(var(--color-border) / <alpha-value>)",
      },
      ringColor: {
        DEFAULT: "rgb(var(--color-accent) / <alpha-value>)",
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(0 0 0 / 0.04), 0 1px 3px 0 rgb(0 0 0 / 0.06)",
      },
      /*
       * Design tokens: type scale, spacing, motion.
       *
       * Type scale (use these instead of ad hoc text-* + font-* combos):
       *   text-page-title     24/32 600  one per page, the h1
       *   text-section-title  18/28 600  h2 section headings
       *   text-card-title     16/24 600  card headings
       *   text-body           14/20 400  default body text
       *   text-small          13/18 400  notes and hints
       *   text-caption        12/16 500  badges, group labels
       *
       * Spacing convention (works with p-*, m-*, gap-*, space-y-*):
       *   page-x   1rem    horizontal page padding
       *   page-y   1.5rem  vertical page padding
       *   section  1.5rem  gap between page sections
       *   card     1rem    card padding
       *   card-lg  1.5rem  modal and dialog padding
       *
       * Motion: durations and easing come from CSS variables on :root in
       * index.css (--motion-fast/base/slow/ease). prefers-reduced-motion
       * shortens them to 1ms there. tailwindcss-animate is intentionally not
       * used; the Toast keyframes below replace it.
       */
      fontSize: {
        "page-title": ["1.5rem", { lineHeight: "2rem", fontWeight: "600" }],
        "section-title": ["1.125rem", { lineHeight: "1.75rem", fontWeight: "600" }],
        "card-title": ["1rem", { lineHeight: "1.5rem", fontWeight: "600" }],
        body: ["0.875rem", { lineHeight: "1.25rem", fontWeight: "400" }],
        small: ["0.8125rem", { lineHeight: "1.125rem", fontWeight: "400" }],
        caption: ["0.75rem", { lineHeight: "1rem", fontWeight: "500" }],
      },
      spacing: {
        "page-x": "1rem",
        "page-y": "1.5rem",
        section: "1.5rem",
        card: "1rem",
        "card-lg": "1.5rem",
      },
      transitionDuration: {
        fast: "var(--motion-fast)",
        base: "var(--motion-base)",
        slow: "var(--motion-slow)",
      },
      transitionTimingFunction: {
        standard: "var(--motion-ease)",
      },
      keyframes: {
        "toast-in": {
          from: { opacity: "0", transform: "translateX(calc(100% + 1rem))" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        "toast-out": { from: { opacity: "1" }, to: { opacity: "0" } },
        "toast-swipe-out": {
          from: { transform: "translateX(var(--radix-toast-swipe-end-x))" },
          to: { transform: "translateX(calc(100% + 1rem))" },
        },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
      },
      animation: {
        "toast-in": "toast-in var(--motion-slow) var(--motion-ease)",
        "toast-out": "toast-out var(--motion-base) var(--motion-ease) forwards",
        "toast-swipe-out":
          "toast-swipe-out var(--motion-base) var(--motion-ease) forwards",
        "fade-in": "fade-in var(--motion-base) var(--motion-ease)",
      },
    },
  },
  plugins: [],
};
