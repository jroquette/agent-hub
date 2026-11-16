import type { RouteObject } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { appRoutes } from "./routes";

// The Toolkit's module arrives only when the test lets it. This file has a module registry of its
// own, so no other test has loaded the Toolkit's code first. It opens one route only: while the
// mock holds a module, Vitest's mocker gives a second import of it the real module at once, so
// the new-draft route has a file of its own (routes.studioNew.test.ts).
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

const EDIT_DRAFT = "projects/:project/skills/:kind/:source/:name/edit";

/** Every route of the table, nested children included, in order. */
function allRoutes(routes: readonly RouteObject[]): RouteObject[] {
  return routes.flatMap((route) => [route, ...allRoutes(route.children ?? [])]);
}

describe("appRoutes", () => {
  it("draws a draft's edit only once the Toolkit's code is in", async () => {
    // An invalid kind redirects to the Toolkit: drawn before its code, the page would be empty.
    const routes = allRoutes(appRoutes).filter((route) => route.path === EDIT_DRAFT);
    expect(routes.map((route) => route.path)).toEqual([EDIT_DRAFT]);
    const [route] = routes;
    if (typeof route?.lazy !== "function") throw new Error(`no lazy on ${EDIT_DRAFT}`);
    const drawn: string[] = [];
    const load = route.lazy().then(() => {
      drawn.push(EDIT_DRAFT);
    });

    // The Studio's own code arrives, and the Toolkit's is still on its way.
    await import("./screens/skills/Studio");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(drawn).toEqual([]);

    toolkit.arrive();
    await load;
    expect(drawn).toEqual([EDIT_DRAFT]);
  });
});
