import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "../../App";
import { ToastProvider } from "../ui";
import { ThemeProvider } from "../../theme/ThemeProvider";
import indexHtml from "../../../index.html?raw";

const publicFiles = import.meta.glob("../../../public/*", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const pngFiles = import.meta.glob("../../../public/*.png", {
  query: "?inline",
  import: "default",
  eager: true,
}) as Record<string, string>;

const byName = (name: string) => publicFiles[`../../../public/${name}`];

describe("AppLayout header brand link", () => {
  it("links to / with the name 'Logstead home' and shows no tagline", () => {
    const { container } = render(
      <ThemeProvider><ToastProvider>
        <MemoryRouter initialEntries={["/"]}>
          <App />
        </MemoryRouter>
      </ToastProvider></ThemeProvider>,
    );
    const link = screen.getByRole("link", { name: "Logstead home" });
    expect(link).toHaveAttribute("href", "/");
    expect(link.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(link.querySelector(".fill-brand-tagline")).toBeNull();
    expect(container.querySelector("header .fill-brand-tagline")).toBeNull();
  });
});

describe("index.html contract", () => {
  const doc = new DOMParser().parseFromString(indexHtml, "text/html");

  it("has the Logstead title", () => {
    expect(doc.title).toBe("Logstead");
  });

  it("links the SVG favicon, 32px PNG favicon, and apple-touch-icon", () => {
    const svg = doc.querySelector('link[rel="icon"][type="image/svg+xml"]');
    expect(svg?.getAttribute("href")).toBe("/favicon.svg");
    const png = doc.querySelector('link[rel="icon"][type="image/png"]');
    expect(png?.getAttribute("sizes")).toBe("32x32");
    expect(png?.getAttribute("href")).toBe("/favicon-32.png");
    expect(doc.querySelector('link[rel="apple-touch-icon"]')?.getAttribute("href")).toBe(
      "/apple-touch-icon.png",
    );
  });
});

describe("public brand assets", () => {
  it.each(["favicon.svg", "favicon-32.png", "apple-touch-icon.png", "logo.svg", "favicon-monogram.svg"])(
    "includes %s",
    (name) => {
      expect(byName(name)).toBeTruthy();
    },
  );

  // Read the PNG IHDR width/height from the inlined base64 data URL.
  const dims = (name: string) => {
    const bin = atob(pngFiles[`../../../public/${name}`].split(",")[1]);
    const n = (o: number) =>
      ((bin.charCodeAt(o) << 24) | (bin.charCodeAt(o + 1) << 16) | (bin.charCodeAt(o + 2) << 8) | bin.charCodeAt(o + 3)) >>> 0;
    return { sig: bin.slice(1, 4), w: n(16), h: n(20) };
  };

  it("favicon-32.png is 32 by 32", () => {
    expect(dims("favicon-32.png")).toEqual({ sig: "PNG", w: 32, h: 32 });
  });

  it("apple-touch-icon.png is 180 by 180", () => {
    expect(dims("apple-touch-icon.png")).toEqual({ sig: "PNG", w: 180, h: 180 });
  });
});
