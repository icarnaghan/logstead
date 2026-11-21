import { describe, expect, it } from "vitest";
import type { RouteObject } from "react-router-dom";
import { APP_ROUTES, leafPaths } from "./routes";

describe("leafPaths", () => {
  it("returns nested route paths joined with their parent prefix", () => {
    const routes: RouteObject[] = [
      { path: "a", children: [{ path: "b", children: [{ path: "c" }] }] },
    ];
    expect(leafPaths(routes)).toEqual(["/a/b/c"]);
  });

  it("passes through pathless layout routes", () => {
    const routes: RouteObject[] = [{ children: [{ path: "x" }, { path: "y" }] }];
    expect(leafPaths(routes)).toEqual(["/x", "/y"]);
  });

  it("maps index routes to their parent's path", () => {
    const routes: RouteObject[] = [
      { index: true },
      { path: "p", children: [{ index: true }, { path: "q" }] },
    ];
    expect(leafPaths(routes)).toEqual(["/", "/p", "/p/q"]);
  });

  it("skips redirect routes", () => {
    const routes: RouteObject[] = [
      {
        path: "imports",
        children: [
          { index: true, handle: { redirect: true } },
          { path: "schedule-e" },
        ],
      },
    ];
    expect(leafPaths(routes)).toEqual(["/imports/schedule-e"]);
  });

  it("keeps parameterized segments and the catch-all as written", () => {
    const routes: RouteObject[] = [
      { path: "properties/:propertyId", children: [{ path: "loans" }] },
      { path: "*" },
    ];
    expect(leafPaths(routes)).toEqual(["/properties/:propertyId/loans", "/*"]);
  });

  describe("APP_ROUTES", () => {
    const paths = leafPaths(APP_ROUTES);

    it("includes nested, index, parameterized and catch-all routes", () => {
      expect(paths).toEqual(
        expect.arrayContaining([
          "/",
          "/imports/schedule-e",
          "/imports/schedule-e/extract",
          "/properties/:propertyId",
          "/properties/:propertyId/transactions",
          "/businesses/:businessId",
          "/accountant-package",
          "/activity",
          "/search",
          "/*",
        ]),
      );
    });

    it("omits the /imports redirect", () => {
      expect(paths).not.toContain("/imports");
    });
  });
});
