import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BrandSplash } from "./BrandSplash";

describe("BrandSplash class contract", () => {
  it("shows the tagline logo only from sm up and a taglineless logo below", () => {
    const { container } = render(<BrandSplash />);
    const svgs = Array.from(container.querySelectorAll("svg"));
    expect(svgs).toHaveLength(2);
    const [small, wide] = svgs;
    expect(small).toHaveClass("h-20", "sm:hidden");
    expect(small.querySelector(".fill-brand-tagline")).toBeNull();
    expect(wide).toHaveClass("hidden", "sm:block", "h-40");
    expect(wide.querySelector(".fill-brand-tagline")).not.toBeNull();
  });
});
