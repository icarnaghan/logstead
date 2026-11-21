import "../../test/apiStub";
import { describe, expect, it } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { Button } from "./Button";
import { Input } from "./Input";
import { Select } from "./Select";
import { Textarea } from "./Textarea";
import { sectionTabClassName } from "../sectionTabStyles";
import { FOCUS_RING } from "./focusRing";
import { MoneyInput } from "./MoneyInput";
import { DateInput } from "./DateInput";
import { ResponsiveTable } from "./ResponsiveTable";
import { ErrorSummary } from "./ErrorSummary";
import { Breadcrumb } from "./Breadcrumb";
import { ToastProvider } from "./toast/ToastProvider";
import { useToast } from "./toast/useToast";
import { MainNav } from "../MainNav";
import { ProfileMenu } from "../ProfileMenu";
import { PhotoLightbox } from "../photos/PhotoLightbox";
import AppLayout from "../AppLayout";
import { PropertySectionTabs } from "../PropertySectionTabs";
import { ChecklistCard } from "../dashboard/ChecklistCard";
import { ThemeProvider } from "../../theme/ThemeProvider";
import type { DashboardSummary } from "../../api/dashboard";

/**
 * Class-contract tests (Requirements 25.4, 25.5, 25.9). jsdom has no layout,
 * so rendered pixel sizes (44px targets) need a manual check on a 375px
 * viewport; these tests render each component and assert the class names that
 * produce them.
 *
 * Three components (PropertyPhotos, ScheduleTable, PropertyEntryCard) keep a
 * source scan: rendering their small text buttons needs a network-backed
 * fixture or a large form model, which costs far more than one class check.
 */
const sources = import.meta.glob("/src/components/**/*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const src = (rel: string) => {
  const text = sources[`/src/components/${rel}`];
  if (text === undefined) throw new Error(`Source not found: ${rel}`);
  return text;
};

const FOCUS_OUTLINE = "focus-visible:outline";

const SOURCE_SCANNED = [
  "photos/PropertyPhotos.tsx",
  "assets/ScheduleTable.tsx",
  "schedule-e-import/PropertyEntryCard.tsx",
];

const crumbs = [{ label: "Home", to: "/" }, { label: "Here" }];
const errors = [{ field: "name", message: "Name is required" }];

describe("touch target class contracts below 768px", () => {
  it("text controls carry max-md:min-h-11", () => {
    render(
      <div>
        <Button>Go</Button>
        <Input aria-label="i" />
        <Select aria-label="s" />
        <Textarea aria-label="t" />
      </div>,
    );
    for (const el of [
      screen.getByRole("button", { name: "Go" }),
      screen.getByLabelText("i"),
      screen.getByLabelText("s"),
      screen.getByLabelText("t"),
    ]) {
      expect(el.className).toContain("max-md:min-h-11");
    }
  });

  it("form controls use 16px text below md and text-sm at md and wider", () => {
    render(
      <div>
        <Input aria-label="i" />
        <Select aria-label="s" />
        <Textarea aria-label="t" />
        <MoneyInput aria-label="m" value="" onValueChange={() => {}} />
        <DateInput aria-label="d" value="" onValueChange={() => {}} />
      </div>,
    );
    for (const name of ["i", "s", "t", "m", "d"]) {
      const cls = screen.getByLabelText(name).className;
      expect(cls).toContain("max-md:text-base");
      expect(cls).toContain("text-sm");
    }
  });
  it("icon buttons carry max-md:h-11 and max-md:w-11", () => {
    render(<Button size="icon" aria-label="x" />);
    const cls = screen.getByRole("button", { name: "x" }).className;
    expect(cls).toContain("max-md:h-11");
    expect(cls).toContain("max-md:w-11");
  });

  it("section tabs carry max-md:min-h-11 in both states", () => {
    expect(sectionTabClassName(true)).toContain("max-md:min-h-11");
    expect(sectionTabClassName(false)).toContain("max-md:min-h-11");
  });
});

describe("additional touch target contracts", () => {
  it("MoneyInput and DateInput inputs carry max-md:min-h-11", () => {
    render(
      <div>
        <MoneyInput aria-label="m" value="" onValueChange={() => {}} />
        <DateInput aria-label="d" value="" onValueChange={() => {}} />
      </div>,
    );
    expect(screen.getByLabelText("m").className).toContain("max-md:min-h-11");
    expect(screen.getByLabelText("d").className).toContain("max-md:min-h-11");
  });

  it("ResponsiveTable sort buttons carry max-md:min-h-11", () => {
    render(
      <ResponsiveTable
        caption="c"
        columns={[{ key: "a", header: "A", sortable: true }]}
        rows={[{ id: "1", cells: { a: "x" } }]}
      />,
    );
    expect(screen.getByRole("button", { name: "A" }).className).toContain(
      "max-md:min-h-11",
    );
  });

  it("MainNav links carry max-md:min-h-11", () => {
    render(
      <MemoryRouter>
        <MainNav />
      </MemoryRouter>,
    );
    const links = screen.getAllByRole("link");
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) expect(link.className).toContain("max-md:min-h-11");
  });

  it("ProfileMenu trigger carries max-md:h-11 and max-md:w-11", () => {
    render(
      <MemoryRouter>
        <ProfileMenu />
      </MemoryRouter>,
    );
    const cls = screen.getByRole("button", { name: /open account menu/i })
      .className;
    expect(cls).toContain("max-md:h-11");
    expect(cls).toContain("max-md:w-11");
  });

  it("PhotoLightbox close button carries max-md:h-11 and max-md:w-11", () => {
    render(
      <PhotoLightbox open onOpenChange={() => {}} src="/p.jpg" alt="Kitchen" />,
    );
    const cls = screen.getByRole("button", { name: "Close photo" }).className;
    expect(cls).toContain("max-md:h-11");
    expect(cls).toContain("max-md:w-11");
  });

  it("ErrorSummary buttons and Breadcrumb links extend their hit area", () => {
    render(
      <MemoryRouter>
        <ErrorSummary items={errors} idFor={(f) => f} />
        <Breadcrumb items={crumbs} />
      </MemoryRouter>,
    );
    for (const el of [
      screen.getByRole("button", { name: "Name is required" }),
      screen.getByRole("link", { name: "Home" }),
    ]) {
      expect(el.className).toContain("relative");
      expect(el.className).toContain("before:absolute before:-inset-2");
    }
  });

  it.each(SOURCE_SCANNED)(
    "%s small text buttons extend hit area with before:-inset-2",
    (file) => {
      const text = src(file);
      expect(text).toContain("before:absolute before:-inset-2");
      expect(text).toContain("relative");
    },
  );
});

describe("polish touch target contracts", () => {
  it("header Search button, tab disclosure button and guide controls carry the 44px classes and focus ring", async () => {
    const summary: DashboardSummary = {
      tax_year: 2024,
      has_properties: true,
      total_income: "0.00",
      total_expenses: "0.00",
      net: "0.00",
      properties: [],
      empty_state_prompt: null,
    };
    render(
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={["/x"]}>
            <AppLayout />
            <PropertySectionTabs propertyId="p1" />
            <ChecklistCard summary={summary} trends={{ years: [] }} loading={false} error={false} />
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>,
    );
    const search = (await screen.findByRole("button", { name: "Search" })).className;
    await waitFor(() => expect(document.querySelector("[aria-busy=true]")).toBeNull());
    expect(search).toContain("max-md:h-11");
    expect(search).toContain("max-md:w-11");
    const disclosure = screen.getByRole("button", { name: /^Property sections:/ }).className;
    expect(disclosure).toContain("min-h-11");
    expect(disclosure).toContain(FOCUS_OUTLINE);
    for (const name of ["Collapse", "Dismiss setup checklist"]) {
      const cls = screen.getByRole("button", { name }).className;
      expect(cls).toContain("max-md:");
      for (const c of FOCUS_RING.split(" ")) expect(cls).toContain(c);
    }
  });
});

describe("focus ring contracts", () => {
  it("FOCUS_RING is a focus-visible outline", () => {
    expect(FOCUS_RING).toContain(FOCUS_OUTLINE);
    expect(FOCUS_RING).toContain("focus-visible:outline-2");
  });

  it("form primitives and buttons include FOCUS_RING classes", () => {
    render(
      <div>
        <Button>Go</Button>
        <Button size="icon" aria-label="ic" />
        <Input aria-label="i" />
        <Select aria-label="s" />
        <Textarea aria-label="t" />
      </div>,
    );
    for (const el of [
      screen.getByRole("button", { name: "Go" }),
      screen.getByRole("button", { name: "ic" }),
      screen.getByLabelText("i"),
      screen.getByLabelText("s"),
      screen.getByLabelText("t"),
    ]) {
      for (const c of FOCUS_RING.split(" ")) expect(el.className).toContain(c);
    }
  });

  it("section tabs have a focus-visible outline in both states", () => {
    expect(sectionTabClassName(true)).toContain(FOCUS_OUTLINE);
    expect(sectionTabClassName(false)).toContain(FOCUS_OUTLINE);
  });

  it("MainNav links, ProfileMenu trigger and PhotoLightbox close have a focus-visible outline", () => {
    render(
      <MemoryRouter>
        <MainNav />
        <ProfileMenu />
      </MemoryRouter>,
    );
    for (const el of [
      ...screen.getAllByRole("link"),
      screen.getByRole("button", { name: /open account menu/i }),
    ]) {
      expect(el.className).toContain(FOCUS_OUTLINE);
    }
    cleanup();
    // The open modal hides everything else from the accessibility tree.
    render(
      <PhotoLightbox open onOpenChange={() => {}} src="/p.jpg" alt="Kitchen" />,
    );
    expect(
      screen.getByRole("button", { name: "Close photo" }).className,
    ).toContain(FOCUS_OUTLINE);
  });

  it.each([
    "photos/PropertyPhotos.tsx",
    "schedule-e-import/PropertyEntryCard.tsx",
  ])("%s uses a focus-visible outline (source scan)", (file) => {
    expect(src(file)).toContain(FOCUS_OUTLINE);
  });

  it("ErrorSummary, Breadcrumb and ResponsiveTable controls include FOCUS_RING", () => {
    render(
      <MemoryRouter>
        <ErrorSummary items={errors} idFor={(f) => f} />
        <Breadcrumb items={crumbs} />
        <ResponsiveTable
          caption="c"
          columns={[{ key: "a", header: "A", sortable: true }]}
          rows={[]}
        />
      </MemoryRouter>,
    );
    for (const el of [
      screen.getByRole("button", { name: "Name is required" }),
      screen.getByRole("link", { name: "Home" }),
      screen.getByRole("button", { name: "A" }),
    ]) {
      for (const c of FOCUS_RING.split(" ")) expect(el.className).toContain(c);
    }
  });

  it("toast dismiss and action buttons are built on the shared Button", async () => {
    function Harness() {
      const { notify } = useToast();
      return (
        <button
          type="button"
          onClick={() =>
            notify({
              variant: "info",
              title: "Hi",
              action: { label: "Undo", onClick: () => {} },
            })
          }
        >
          fire
        </button>
      );
    }
    render(
      <ToastProvider>
        <Harness />
      </ToastProvider>,
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "fire" }));
    const dismiss = await screen.findByRole("button", {
      name: "Dismiss notification",
    });
    expect(dismiss.className).toContain("max-md:h-11");
    for (const c of FOCUS_RING.split(" ")) expect(dismiss.className).toContain(c);
    expect(screen.getByRole("button", { name: "Undo" }).className).toContain(
      "max-md:min-h-11",
    );
  });
});
