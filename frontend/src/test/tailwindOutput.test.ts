// Configuration test: runs the real PostCSS + Tailwind pipeline with the real
// tailwind.config.js over the ToastProvider source and index.css, so a missing
// plugin or typo'd class (the original `animate-in` bug) fails here instead of
// silently generating no CSS. jsdom tests cannot see the compiled stylesheet.
import { beforeAll, describe, expect, it } from "vitest";
import postcss from "postcss";
import tailwindcss from "tailwindcss";
import resolveConfig from "tailwindcss/resolveConfig";
import toastSource from "../components/ui/toast/ToastProvider.tsx?raw";
import indexCss from "../index.css?raw";
// @ts-expect-error The JS config has no type declarations.
import rawConfig from "../../tailwind.config.js";

type TailwindConfig = Parameters<typeof resolveConfig>[0];

const config = rawConfig as TailwindConfig;
let css = "";

beforeAll(async () => {
  const result = await postcss([
    tailwindcss({
      ...config,
      content: [{ raw: toastSource, extension: "tsx" }],
    } as TailwindConfig),
  ]).process(indexCss, { from: undefined });
  css = result.css;
});

describe("Tailwind output", () => {
  it.each(["toast-in", "toast-out", "toast-swipe-out"])(
    "emits the .animate-%s utility and its @keyframes",
    (name) => {
      // The utility is used in ToastProvider only inside data-[...] variants,
      // so match the class name allowing for an escaped variant prefix.
      expect(css).toMatch(new RegExp(`\\.[^{]*animate-${name}[^{]*\\{`));
      expect(css).toMatch(new RegExp(`@keyframes ${name}\\s*\\{`));
    },
  );

  it("does not emit the removed tailwindcss-animate classes", () => {
    expect(css).not.toMatch(/\.[^{]*animate-in\b/);
    expect(css).not.toMatch(/\.[^{]*animate-out\b/);
  });

  it("includes the prefers-reduced-motion rule with 1ms durations", () => {
    const match = css.match(
      /@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*?\}\s*\}/,
    );
    expect(match).not.toBeNull();
    const rule = match![0];
    expect(rule).toMatch(/animation-duration:\s*1ms/);
    expect(rule).toMatch(/transition-duration:\s*1ms/);
    expect(rule).toMatch(/animation-iteration-count:\s*1\b/);
  });
});

describe("resolved config tokens", () => {
  it("defines the type scale", () => {
    const { fontSize } = resolveConfig(config).theme;
    for (const key of [
      "page-title",
      "section-title",
      "card-title",
      "body",
      "small",
      "caption",
    ]) {
      expect(fontSize).toHaveProperty(key);
    }
  });

  it("defines the spacing entries", () => {
    const { spacing } = resolveConfig(config).theme;
    for (const key of ["page-x", "page-y", "section", "card", "card-lg"]) {
      expect(spacing).toHaveProperty(key);
    }
  });
});
