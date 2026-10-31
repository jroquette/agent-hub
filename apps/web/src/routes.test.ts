import type { RouteObject } from "react-router";
import { describe, expect, it } from "vitest";

import { appRoutes } from "./routes";

/** Every route of the table, nested children included, in order. */
function allRoutes(routes: readonly RouteObject[]): RouteObject[] {
  return routes.flatMap((route) => [route, ...allRoutes(route.children ?? [])]);
}

/** A routed entry's name in a failure message. */
function routeName(route: RouteObject): string {
  return route.index === true ? "(index)" : (route.path ?? "");
}

// The redirects routes.tsx defines itself, in table order: `live` (LiveRedirect), `knowledge` and
// `settings` (Navigate). LegacyWorkflowRedirect is not one of them: it lives in screens/workflows.
const OWN_REDIRECTS = ["live", "knowledge", "settings"];

// 48 routes have a path or an index: the 3 redirects, and 45 routed screens (42 screens and
// LegacyWorkflowRedirect, with LearningsScreen and NewWorkflowScreen on two paths each).
const ROUTED_SCREENS = 45;

describe("appRoutes", () => {
  it("loads each routed screen on demand, redirects excepted", () => {
    const routed = allRoutes(appRoutes).filter(
      (route) => route.index === true || route.path !== undefined,
    );
    const isOwnRedirect = (route: RouteObject) => OWN_REDIRECTS.includes(route.path ?? "");
    const screens = routed.filter((route) => !isOwnRedirect(route));

    expect(routed.filter(isOwnRedirect).map(routeName)).toEqual(OWN_REDIRECTS);
    expect(screens).toHaveLength(ROUTED_SCREENS);
    const eager = screens.filter(
      (route) =>
        route.lazy === undefined || route.element !== undefined || route.Component !== undefined,
    );
    expect(eager.map(routeName)).toEqual([]);
  });

  it("loads each redirect's target code before it redirects", () => {
    // A redirect drawn at once would empty main#main, and move the address and the nav, while
    // the target screen's code still loads.
    const redirects = allRoutes(appRoutes).filter((route) =>
      OWN_REDIRECTS.includes(route.path ?? ""),
    );

    expect(redirects.map(routeName)).toEqual(OWN_REDIRECTS);
    const atOnce = redirects.filter(
      (route) =>
        route.lazy === undefined || route.element !== undefined || route.Component !== undefined,
    );
    expect(atOnce.map(routeName)).toEqual([]);
  });
});
