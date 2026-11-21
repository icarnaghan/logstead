import type { ReactElement } from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { PageContainer } from "./PageContainer";
import DashboardPage from "../pages/DashboardPage";
import PropertyDetailPage from "../pages/PropertyDetailPage";
import AssetsPage from "../pages/AssetsPage";
import ReportsPage from "../pages/ReportsPage";
import PropertiesPage from "../pages/PropertiesPage";
import ProfilePage from "../pages/ProfilePage";
import ImportReviewPage from "../pages/ImportReviewPage";
import NotFoundPage from "../pages/NotFoundPage";
import { ThemeProvider } from "../theme/ThemeProvider";
import { ToastProvider } from "../components/ui";

// ReportsPage's year-range hook calls getEarliestDataYear; resolve null so the
// ReportsPage case does not hit the network.
vi.mock("../api/properties", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/properties")>()),
  getEarliestDataYear: vi.fn().mockResolvedValue(null),
}));

/**
 * Structural + hard-boundary + accessibility tests for the Section 2 layout
 * polish (task 5.3).
 *
 * These lock in the Requirement 8/9/10/11 contract for the `PageContainer`
 * width convention and the Panel_Page / out-of-scope split:
 * - PageContainer renders a plain `<div>` with only width/spacing utilities,
 *   defaults to the widened `max-w-screen-2xl`, offers a `narrow` `max-w-6xl`
 *   variant, and adds no landmark/heading/focusable element (Req 8.1, 8.2,
 *   11.1, 11.2).
 * - The hard boundary (Req 10): the wrapper carries no color, typography,
 *   radius, shadow, or design-token classes — layout/spacing only.
 * - Panel_Pages adopt the widened container; out-of-scope pages do not
 *   (Req 8.1–8.3). This is asserted by RENDERING each page and probing the DOM
 *   for the widened `max-w-screen-2xl` wrapper — no filesystem/source reads.
 * - axe reports no violations over PageContainer with sample content (Req 11.3).
 *
 * The Panel_Page landmark/focus-order/axe preservation (Req 11.1–11.3) is
 * additionally covered by the existing page suites (AppLayout.test.tsx,
 * DashboardPage.test.tsx, ReportsPage.test.tsx, PropertyDetailPage.test.tsx)
 * which stay green after the layout change.
 */

/** The single `<div>` PageContainer renders (its only element). */
function renderContainer(width?: "wide" | "narrow") {
  const { container } = render(
    width ? (
      <PageContainer width={width}>
        <p>child content</p>
      </PageContainer>
    ) : (
      <PageContainer>
        <p>child content</p>
      </PageContainer>
    ),
  );
  return container.firstElementChild as HTMLElement;
}

describe("PageContainer — structural width convention (Req 8.1, 8.2)", () => {
  it("renders a plain div with the widened width class by default", () => {
    const root = renderContainer();

    expect(root.tagName).toBe("DIV");
    expect(root.className).toContain("max-w-screen-2xl");
    // The default must be the WIDE variant, never the narrow prior width.
    expect(root.className).not.toContain("max-w-6xl");
  });

  it("renders the narrow prior-width class when width=\"narrow\"", () => {
    const root = renderContainer("narrow");

    expect(root.className).toContain("max-w-6xl");
    expect(root.className).not.toContain("max-w-screen-2xl");
  });

  it("applies only the mx-auto/w-full/max-w-*/space-y-section layout utilities", () => {
    const classes = renderContainer().className.trim().split(/\s+/);

    // Exactly the width + spacing utility set — nothing else sneaks in.
    expect(new Set(classes)).toEqual(
      new Set(["mx-auto", "w-full", "max-w-screen-2xl", "space-y-section"]),
    );
  });

  it("renders its children", () => {
    renderContainer();
    expect(screen.getByText("child content")).toBeInTheDocument();
  });
});

describe("PageContainer — adds no landmark/heading/focusable element (Req 11.1, 11.2)", () => {
  it("introduces no landmark role, heading, or focusable element of its own", () => {
    const { container } = render(
      <PageContainer>
        <span>inert child</span>
      </PageContainer>,
    );

    const root = container.firstElementChild as HTMLElement;

    // A bare, non-semantic div: no implicit/explicit landmark role.
    expect(root.getAttribute("role")).toBeNull();
    expect(root.tagName).toBe("DIV");

    // No heading and no focusable control contributed by the wrapper itself
    // (the only descendant is the inert child we passed in).
    expect(container.querySelector("h1,h2,h3,h4,h5,h6")).toBeNull();
    expect(
      container.querySelector(
        "a[href],button,input,select,textarea,[tabindex]",
      ),
    ).toBeNull();
  });
});

describe("PageContainer — hard boundary: layout/spacing only (Req 10.1–10.6)", () => {
  // Guard against any visual-restyle class ever being added to the wrapper:
  // colors, typography/type-scale, radii, shadows, or token-backed styling.
  const FORBIDDEN = [
    { label: "background color", re: /\bbg-/ },
    { label: "text/typography color", re: /\btext-/ },
    { label: "border color/width", re: /\bborder(-|\b)/ },
    { label: "font family/weight", re: /\bfont-/ },
    { label: "border radius", re: /\brounded(-|\b)/ },
    { label: "shadow", re: /\bshadow(-|\b)/ },
    { label: "ring", re: /\bring(-|\b)/ },
  ];

  it.each(FORBIDDEN)(
    "carries no $label class on the rendered wrapper",
    ({ re }) => {
      for (const width of ["wide", "narrow"] as const) {
        const classes = renderContainer(width).className;
        expect(re.test(classes)).toBe(false);
      }
    },
  );
});

describe("Panel_Pages adopt the widened container; out-of-scope pages do not (Req 8.1–8.3)", () => {
  // No-op async loaders keep each render self-contained and network-free. The
  // `PageContainer` is the top-level wrapper for every Panel_Page, so the
  // widened `max-w-screen-2xl` is present synchronously on first render — the
  // async tiles below it never need to settle for this structural probe.
  const noop = <T,>(value: T) => async () => value;

  function withProviders(ui: ReactElement, initialPath = "/") {
    return render(
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[initialPath]}>{ui}</MemoryRouter>
        </ToastProvider>
      </ThemeProvider>,
    );
  }

  /** Mounts a page at a `:propertyId` route so `useParams()` resolves. */
  function withPropertyRoute(
    path: string,
    element: ReactElement,
    initialPath: string,
  ) {
    return withProviders(
      <Routes>
        <Route path={path} element={element} />
      </Routes>,
      initialPath,
    );
  }

  it("DashboardPage adopts the widened PageContainer", () => {
    const { container } = withProviders(
      <DashboardPage
        api={
          {
            getDashboard: noop({
              tax_year: 2024,
              has_properties: false,
              total_income: "0.00",
              total_expenses: "0.00",
              net: "0.00",
              properties: [],
              empty_state_prompt: null,
            }),
            getPropertySummaries: noop([]),
            getTrends: noop({ years: [] }),
          } as unknown as import("../api/dashboard").DashboardApi
        }
      />,
    );

    expect(container.querySelector(".max-w-screen-2xl")).not.toBeNull();
  });

  it("PropertyDetailPage adopts the widened PageContainer", () => {
    const { container } = withPropertyRoute(
      "/properties/:propertyId",
      <PropertyDetailPage
        loadReport={noop({
          header: {
            property_id: "p1",
            property_name: "Maple Duplex",
            address: "1 Maple St",
            property_type: "Single Family",
            tax_year: 2024,
            fair_rental_days: 0,
            personal_use_days: 0,
          },
          lines: [],
          other_items: [],
          totals: {
            total_income: "0.00",
            total_expenses: "0.00",
            net: "0.00",
          },
        })}
        loadPhotos={noop([])}
        loadAssets={noop([])}
        loadEarliestYear={noop(null)}
        loadNote={noop("")}
        saveNote={async (_id, text) => text}
      />,
      "/properties/p1",
    );

    expect(container.querySelector(".max-w-screen-2xl")).not.toBeNull();
  });

  it("AssetsPage adopts the widened PageContainer", () => {
    const { container } = withPropertyRoute(
      "/properties/:propertyId/assets",
      <AssetsPage
        api={{
          listAssets: vi.fn().mockResolvedValue([]),
          createAsset: vi.fn(),
          updateAsset: vi.fn(),
          deleteAsset: vi.fn(),
          getSchedule: vi.fn().mockResolvedValue([]),
        }}
      />,
      "/properties/p1/assets",
    );

    expect(container.querySelector(".max-w-screen-2xl")).not.toBeNull();
  });

  it("ReportsPage adopts the widened PageContainer", () => {
    const { container } = withPropertyRoute(
      "/properties/:propertyId/reports",
      <ReportsPage
        api={{ getReport: vi.fn().mockResolvedValue(undefined) }}
        years={[2024, 2023]}
      />,
      "/properties/p1/reports",
    );

    expect(container.querySelector(".max-w-screen-2xl")).not.toBeNull();
  });

  it("PropertiesPage keeps its prior width (no widened PageContainer)", () => {
    const { container } = withProviders(
      <PropertiesPage load={noop([])} loadPhotos={noop([])} />,
    );

    expect(container.querySelector(".max-w-screen-2xl")).toBeNull();
  });

  it("ProfilePage keeps its prior width (no widened PageContainer)", () => {
    const { container } = withProviders(<ProfilePage />);

    expect(container.querySelector(".max-w-screen-2xl")).toBeNull();
  });

  it("ImportReviewPage keeps its prior width (no widened PageContainer)", () => {
    const { container } = withPropertyRoute(
      "/properties/:propertyId/import",
      <ImportReviewPage />,
      "/properties/p1/import",
    );

    expect(container.querySelector(".max-w-screen-2xl")).toBeNull();
  });

  it("NotFoundPage keeps its prior width (no widened PageContainer)", () => {
    const { container } = withProviders(<NotFoundPage />);

    expect(container.querySelector(".max-w-screen-2xl")).toBeNull();
  });
});

describe("PageContainer — accessibility (Req 11.3)", () => {
  it("has no detectable axe violations with sample content", async () => {
    const { container } = render(
      // Sample children with a landmark + heading so axe exercises real
      // structure through the wrapper. jsdom cannot compute rendered colors,
      // so color-contrast is disabled as elsewhere in the suite.
      <PageContainer>
        <main aria-labelledby="pc-heading">
          <h1 id="pc-heading">Sample page</h1>
          <p>Body content inside the page container.</p>
        </main>
      </PageContainer>,
    );

    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
