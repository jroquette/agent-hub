import type { RouteObject } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { appRoutes } from "./routes";

// The screen modules the redirects open a screen of, noted when their code first loads.
const loaded = vi.hoisted(() => new Set<string>());
vi.mock("./screens/sessions-list", (importOriginal) => {
  loaded.add("sessions-list");
  return importOriginal();
});
vi.mock("./screens/learnings", (importOriginal) => {
  loaded.add("learnings");
  return importOriginal();
});
vi.mock("./screens/settings", (importOriginal) => {
  loaded.add("settings");
  return importOriginal();
});

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

// The screen module of the page each redirect opens: /sessions, /knowledge/learnings and
// /settings/hubs.
const REDIRECT_TARGETS: Record<string, string> = {
  live: "sessions-list",
  knowledge: "learnings",
  settings: "settings",
};

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

  it("loads the code of the screen each redirect opens, before it redirects", async () => {
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
    for (const redirect of redirects) {
      const target = REDIRECT_TARGETS[routeName(redirect)] ?? "";
      expect(loaded.has(target), `${target} loaded before /${routeName(redirect)}`).toBe(false);
      if (typeof redirect.lazy !== "function") throw new Error(`no lazy on ${routeName(redirect)}`);

      await redirect.lazy();

      expect(loaded.has(target), `/${routeName(redirect)} did not load ${target}`).toBe(true);
    }
  });
});
