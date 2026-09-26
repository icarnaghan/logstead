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
      borderColor: {
        DEFAULT: "rgb(var(--color-border) / <alpha-value>)",
      },
      ringColor: {
        DEFAULT: "rgb(var(--color-accent) / <alpha-value>)",
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(0 0 0 / 0.04), 0 1px 3px 0 rgb(0 0 0 / 0.06)",
      },
    },
  },
  plugins: [],
};
