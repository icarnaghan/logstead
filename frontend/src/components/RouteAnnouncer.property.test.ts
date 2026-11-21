import { createElement } from "react";
import { act, cleanup, render } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import fc from "fast-check";
import { afterEach, describe, expect, it } from "vitest";
import { RouteAnnouncer, shouldHandleRouteChange } from "./RouteAnnouncer";

const segment = fc.constantFrom("a", "b", "c", "properties", "reports");
const pathname = fc
  .array(segment, { minLength: 0, maxLength: 3 })
  .map((parts) => "/" + parts.join("/"));
const search = fc.constantFrom("", "?x=1", "?y=2");
const hash = fc.constantFrom("", "#top", "#section");

describe("RouteAnnouncer (property tests)", () => {
  afterEach(cleanup);

  // Feature: ui-polish-and-consistency, Property 3: Route changes are handled only for pathname changes after the first render
  // **Validates: Requirements 5.5, 5.7**
  it("Property 3: shouldHandleRouteChange is true iff not initial and pathname differs", () => {
    fc.assert(
      fc.property(pathname, pathname, fc.boolean(), (prev, next, isInitial) => {
        expect(shouldHandleRouteChange(prev, next, isInitial)).toBe(
          !isInitial && prev !== next,
        );
      }),
      { numRuns: 100 },
    );
  });

  // Feature: ui-polish-and-consistency, Property 3: Route changes are handled only for pathname changes after the first render
  // **Validates: Requirements 5.5, 5.7**
  it("Property 3: the mounted component moves focus only on pathname changes after first render", () => {
    fc.assert(
      fc.property(
        pathname,
        fc.array(fc.tuple(pathname, search, hash), { minLength: 1, maxLength: 6 }),
        (start, steps) => {
          let navigate: ReturnType<typeof useNavigate> | undefined;
          function Harness() {
            navigate = useNavigate();
            return createElement(
              "div",
              null,
              createElement(RouteAnnouncer),
              createElement(
                "main",
                { id: "main-content", tabIndex: -1 },
                createElement("h1", null, "Title"),
                createElement("button", { id: "other" }, "other"),
              ),
            );
          }

          const { container, unmount } = render(
            createElement(
              MemoryRouter,
              { initialEntries: [start] },
              createElement(Harness),
            ),
          );
          const h1 = container.querySelector("main h1") as HTMLElement;
          const other = container.querySelector("#other") as HTMLElement;

          // First render never moves focus.
          expect(document.activeElement).not.toBe(h1);

          let current = start;
          for (const [path, s, h] of steps) {
            other.focus();
            act(() => {
              navigate!(path + s + h);
            });
            if (path !== current) {
              expect(document.activeElement).toBe(h1);
            } else {
              expect(document.activeElement).toBe(other);
            }
            current = path;
          }
          unmount();
        },
      ),
      { numRuns: 100 },
    );
  });
});
