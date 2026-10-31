import { act, render, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import type { ComponentType } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import type { RouteObject } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { AppShell } from "./shell/AppShell";
import { lazyScreen, RouteSkeleton } from "./shell/routeLoading";
import {
  aPage,
  aProjectSummary,
  stubApi,
  stubEventSource,
  testQueryClient,
  TestProviders,
} from "./testing/builders";
import { appRoutes, HubGate } from "./routes";

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
vi.mock("./screens/skills", (importOriginal) => {
  loaded.add("skills");
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

  it("loads the Toolkit's code with the /workflows screen, which only redirects there", async () => {
    const [workflows] = allRoutes(appRoutes).filter((route) => route.path === "workflows");
    expect(loaded.has("skills")).toBe(false);
    if (typeof workflows?.lazy !== "function") throw new Error("no lazy on workflows");

    await workflows.lazy();

    expect(loaded.has("skills")).toBe(true);
  });
});

/** A screen stand-in: its level-1 heading. */
function standIn(heading: string): ComponentType {
  return () => createElement("h1", null, heading);
}

describe("HubGate", () => {
  it("keeps the page drawn while Welcome's code loads, when no hub is registered", async () => {
    stubApi({ "/api/v1/hubs": aPage([]), "/api/v1/projects": aPage([aProjectSummary()]) });
    stubEventSource();
    let arrive: () => void = () => undefined;
    const welcomeCode = new Promise<{ WelcomeScreen: ComponentType }>((loaded) => {
      arrive = () => {
        loaded({ WelcomeScreen: standIn("Welcome stand-in") });
      };
    });
    const portfolio = { PortfolioScreen: standIn("Portfolio stand-in") };
    const gated: RouteObject = {
      element: createElement(HubGate),
      children: [
        { index: true, ...lazyScreen(() => Promise.resolve(portfolio), "PortfolioScreen") },
      ],
    };
    const welcome = { path: "welcome", ...lazyScreen(() => welcomeCode, "WelcomeScreen") };
    const router = createMemoryRouter(
      [
        {
          element: createElement(AppShell),
          children: [
            { hydrateFallbackElement: createElement(RouteSkeleton), children: [gated, welcome] },
          ],
        },
      ],
      { initialEntries: ["/"] },
    );
    render(
      createElement(TestProviders, {
        client: testQueryClient(),
        children: createElement(RouterProvider, { router }),
      }),
    );
    await screen.findByRole("heading", { level: 1, name: "Portfolio stand-in" });

    // The hub list is empty, so the gate heads for /welcome, whose code has not arrived. Checked
    // often: past 300 ms the page skeleton would take the page's place anyway.
    await waitFor(
      () => {
        expect(router.state.navigation.location?.pathname).toBe("/welcome");
      },
      { interval: 5 },
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "Portfolio stand-in" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");

    await act(async () => {
      arrive();
      await welcomeCode;
    });
    expect(
      await screen.findByRole("heading", { level: 1, name: "Welcome stand-in" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Portfolio stand-in" })).toBeNull();
    expect(router.state.location.pathname).toBe("/welcome");
    expect(router.state.historyAction).toBe("REPLACE");
  });
});
