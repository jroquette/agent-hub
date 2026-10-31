import type { RouteObject } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { appRoutes } from "./routes";

// The Toolkit's module arrives only when the test lets it. This file has a module registry of its
// own, so no other test has loaded the Toolkit's code first.
const toolkit = vi.hoisted(() => {
  let open: () => void = () => undefined;
  const arrived = new Promise<void>((resolve) => {
    open = resolve;
  });
  return {
    arrived,
    arrive: () => {
      open();
    },
  };
});
vi.mock("./screens/skills", async (importOriginal) => {
  await toolkit.arrived;
  return importOriginal();
});

// The Studio's routes that send an invalid kind to the Toolkit, in table order.
const TOOLKIT_FALLBACKS = [
  "projects/:project/skills/new/:kind",
  "projects/:project/skills/:kind/:source/:name/edit",
];

/** Every route of the table, nested children included, in order. */
function allRoutes(routes: readonly RouteObject[]): RouteObject[] {
  return routes.flatMap((route) => [route, ...allRoutes(route.children ?? [])]);
}

describe("appRoutes", () => {
  it("draws a new draft or a draft's edit only once the Toolkit's code is in", async () => {
    // An invalid kind redirects to the Toolkit: drawn before its code, the page would be empty.
    const routes = allRoutes(appRoutes).filter((route) =>
      TOOLKIT_FALLBACKS.includes(route.path ?? ""),
    );
    expect(routes.map((route) => route.path)).toEqual(TOOLKIT_FALLBACKS);
    const drawn: string[] = [];
    const loads = routes.map(async (route) => {
      if (typeof route.lazy !== "function") throw new Error(`no lazy on ${route.path ?? ""}`);
      await route.lazy();
      drawn.push(route.path ?? "");
    });

    // The Studio's own code arrives, and the Toolkit's is still on its way.
    await import("./screens/skills/Studio");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(drawn).toEqual([]);

    toolkit.arrive();
    await Promise.all(loads);
    expect(drawn.toSorted()).toEqual(TOOLKIT_FALLBACKS.toSorted());
  });
});
