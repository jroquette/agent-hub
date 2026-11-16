import { act, render, screen } from "@testing-library/react";
import { createElement } from "react";
import type { ComponentType } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import type { RouteObject } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiKey } from "./lib/api";
import { AppShell } from "./shell/AppShell";
import { lazyRedirect, lazyScreen, Redirect, RouteSkeleton } from "./shell/routeLoading";
import {
  aPage,
  aProblem,
  aProjectSummary,
  aShellView,
  stubApi,
  stubEventSource,
  testQueryClient,
  TestProviders,
  type ApiRoutes,
} from "./testing/builders";
import { appRoutes, askForHubList, HubGate } from "./routes";

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
// `settings` (Redirect). LegacyWorkflowRedirect is not one of them: it lives in screens/workflows.
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

/** A screen module the test delivers itself: `load` stands for its `import()`. */
function heldModule<Module>(module: Module) {
  let deliver: (value: Module) => void = () => undefined;
  const loaded = new Promise<Module>((resolve) => {
    deliver = resolve;
  });
  return {
    load: () => loaded,
    /** The module arrives, and the router takes it. */
    arrive: async () => {
      await act(async () => {
        deliver(module);
        await loaded;
      });
    },
  };
}

/** Holds the stubbed answers to the requests for `paths` until the returned call; after stubApi. */
function holdAnswers(paths: readonly string[]): () => Promise<void> {
  const fetchMock = vi.mocked(globalThis.fetch);
  const answer = fetchMock.getMockImplementation();
  if (answer === undefined) throw new Error("holdAnswers: call stubApi first");
  let open: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => {
    open = resolve;
  });
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    if (!paths.includes(new URL(request.url).pathname)) return answer(input, init);
    return gate.then(() => answer(input, init));
  });
  return async () => {
    await act(async () => {
      open();
      await gate;
    });
  };
}

/** Moves the fake clock by `ms`, then renders what its timers changed. */
function wait(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

/** Lets answered requests, the router and the queries' 0 ms notifications run their course. */
async function settle() {
  for (let turn = 0; turn < 10; turn += 1) {
    await act(async () => {
      await Promise.resolve();
    });
    wait(0);
  }
}

/** With no hub registered: the shell read counts no hub, and the hub list is empty. */
function stubNoHub(api: ApiRoutes = {}) {
  stubApi({
    "/api/v1/screens/shell": aShellView({ hub_count: 0 }),
    "/api/v1/hubs": aPage([]),
    "/api/v1/projects": aPage([aProjectSummary()]),
    ...api,
  });
  stubEventSource();
}

/** The app's route shape: the shell, then a pathless route whose fallback covers a first load. */
function shellRoutes(children: RouteObject[]): RouteObject[] {
  return [
    {
      element: createElement(AppShell),
      children: [{ hydrateFallbackElement: createElement(RouteSkeleton), children }],
    },
  ];
}

/** The app's shape around the gate: the shell, the first-load fallback, the gated pages, Welcome. */
function gatedRoutes(
  pages: RouteObject[],
  welcome: () => Promise<{ WelcomeScreen: ComponentType }>,
): RouteObject[] {
  return shellRoutes([
    { element: createElement(HubGate), children: pages },
    { path: "welcome", ...lazyScreen(welcome, "WelcomeScreen") },
  ]);
}

interface HeldRoute {
  route: RouteObject;
  /** The route's code arrives, and the router takes it. */
  arrive: () => Promise<void>;
}

/**
 * The route `path` of the real table, whose code arrives only when the test calls `arrive`: a
 * first load of it is slow. Its own code is loaded once first, so it is quick on the fake clock.
 */
async function heldRealRoute(path: string): Promise<HeldRoute> {
  const [route] = allRoutes(appRoutes).filter((each) => each.path === path);
  const lazy = route?.lazy;
  if (typeof lazy !== "function") throw new Error(`no lazy on ${path}`);
  await lazy();
  let open: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => {
    open = resolve;
  });
  return {
    route: {
      path,
      lazy: async () => {
        await gate;
        return lazy();
      },
    },
    arrive: async () => {
      await act(async () => {
        open();
        await gate;
      });
      await settle();
    },
  };
}

/** A route that lands after the router's next turn, on a stand-in with the heading `heading`. */
function standInRoute(path: string, heading: string): RouteObject {
  return { path, lazy: () => Promise.resolve({ element: createElement(standIn(heading)) }) };
}

/** Opens `path` on `routes`, with the queries in `client`; returns the router. */
function openAt(routes: RouteObject[], path: string, client = testQueryClient()) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    createElement(TestProviders, {
      client,
      children: createElement(RouterProvider, { router }),
    }),
  );
  return router;
}

// The shell read's key with no project in scope: the shell, the gate and the app's early
// request all ask for it under this one key.
const SHELL_READ = apiKey("/api/v1/screens/shell", { query: { project: null } });

const main = () => screen.getByRole("main");
const skeleton = () => main().querySelector(".ah-skel");

describe("HubGate", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps the page drawn while the hub list loads, and only redirects once it is empty", async () => {
    vi.useFakeTimers();
    stubNoHub();
    const answerShell = holdAnswers(["/api/v1/screens/shell"]);
    const welcome = heldModule({ WelcomeScreen: standIn("Welcome stand-in") });
    const portfolio = { PortfolioScreen: standIn("Portfolio stand-in") };
    const router = openAt(
      gatedRoutes(
        [{ index: true, ...lazyScreen(() => Promise.resolve(portfolio), "PortfolioScreen") }],
        welcome.load,
      ),
      "/",
    );
    await settle();
    expect(
      screen.getByRole("heading", { level: 1, name: "Portfolio stand-in" }),
    ).toBeInTheDocument();
    expect(router.state.navigation.state).toBe("idle");

    // The shell read counts no hub: the gate heads for /welcome, whose code has not arrived,
    // and draws nothing of the page meanwhile.
    await answerShell();
    await settle();
    expect(router.state.navigation.location?.pathname).toBe("/welcome");
    expect(router.state.location.pathname).toBe("/");
    expect(screen.queryByRole("heading", { name: "Portfolio stand-in" })).toBeNull();

    await welcome.arrive();
    await settle();
    expect(screen.getByRole("heading", { level: 1, name: "Welcome stand-in" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/welcome");
    expect(router.state.historyAction).toBe("REPLACE");
  });

  it("keeps the page drawn once the hub list cannot be read", async () => {
    vi.useFakeTimers();
    stubNoHub({ "/api/v1/screens/shell": aProblem() });
    const client = testQueryClient();
    const welcome = heldModule({ WelcomeScreen: standIn("Welcome stand-in") });
    const portfolio = { PortfolioScreen: standIn("Portfolio stand-in") };
    const router = openAt(
      gatedRoutes(
        [{ index: true, ...lazyScreen(() => Promise.resolve(portfolio), "PortfolioScreen") }],
        welcome.load,
      ),
      "/",
      client,
    );
    await settle();

    // The failed answer is in, and the gate does not take it for an empty list.
    expect(client.getQueryState(SHELL_READ)?.status).toBe("error");
    expect(router.state.navigation.state).toBe("idle");
    expect(router.state.location.pathname).toBe("/");
    expect(
      screen.getByRole("heading", { level: 1, name: "Portfolio stand-in" }),
    ).toBeInTheDocument();
  });

  it("never draws the page on a first load whose hub list is in before the page's code", async () => {
    vi.useFakeTimers();
    stubNoHub();
    const drawn = vi.fn();
    const portfolio = heldModule({
      PortfolioScreen: () => {
        drawn();
        return createElement("h1", null, "Portfolio stand-in");
      },
    });
    const welcome = heldModule({ WelcomeScreen: standIn("Welcome stand-in") });
    // As the app does, the shell read is asked for before the router starts loading the page's
    // code, under the key the shell and the gate read.
    const client = testQueryClient();
    askForHubList(client);
    expect(client.getQueryState(SHELL_READ)?.fetchStatus).toBe("fetching");
    const router = openAt(
      gatedRoutes(
        [{ index: true, ...lazyScreen(portfolio.load, "PortfolioScreen") }],
        welcome.load,
      ),
      "/",
      client,
    );
    // The shell is drawn, and the empty list is in, while the Portfolio's code loads.
    await settle();

    await portfolio.arrive();
    await settle();
    expect(router.state.navigation.location?.pathname).toBe("/welcome");
    await welcome.arrive();
    await settle();

    expect(screen.getByRole("heading", { level: 1, name: "Welcome stand-in" })).toBeInTheDocument();
    expect(drawn).not.toHaveBeenCalled();
  });

  it("never shows the Portfolio's empty state once the hub list comes back empty", async () => {
    const portfolio = await import("./screens/portfolio");
    vi.useFakeTimers();
    stubNoHub({
      "/api/v1/projects": aPage([]),
      "/api/v1/needs-you": aPage([]),
      "/api/v1/activity": aPage([]),
    });
    const answerPortfolio = holdAnswers([
      "/api/v1/projects",
      "/api/v1/needs-you",
      "/api/v1/activity",
    ]);
    const welcome = heldModule({ WelcomeScreen: standIn("Welcome stand-in") });
    const router = openAt(
      gatedRoutes(
        [{ index: true, ...lazyScreen(() => Promise.resolve(portfolio), "PortfolioScreen") }],
        welcome.load,
      ),
      "/",
    );
    await settle();
    expect(router.state.navigation.location?.pathname).toBe("/welcome");

    // The Portfolio's own answers arrive while Welcome's code still loads.
    await answerPortfolio();
    await settle();
    wait(200);
    expect(screen.queryByText("Nothing needs you.")).toBeNull();
    expect(screen.queryByText(/No registered hub has a project in this scope/)).toBeNull();

    await welcome.arrive();
    await settle();
    expect(screen.getByRole("heading", { level: 1, name: "Welcome stand-in" })).toBeInTheDocument();
    expect(screen.queryByText("Nothing needs you.")).toBeNull();
  });

  it("keeps one page skeleton until Welcome renders, when it redirects on a slow first load", async () => {
    vi.useFakeTimers();
    stubNoHub();
    const portfolio = heldModule({ PortfolioScreen: standIn("Portfolio stand-in") });
    const welcome = heldModule({ WelcomeScreen: standIn("Welcome stand-in") });
    const router = openAt(
      gatedRoutes(
        [{ index: true, ...lazyScreen(portfolio.load, "PortfolioScreen") }],
        welcome.load,
      ),
      "/",
    );
    const welcomed = () => screen.queryByRole("heading", { name: "Welcome stand-in" }) !== null;
    // From its first bars until Welcome renders, the skeleton holds main: never the page, never a gap.
    const held = (when: string) => {
      expect(welcomed() || skeleton() !== null, `skeleton ${when}`).toBe(true);
      expect(screen.queryByRole("heading", { name: "Portfolio stand-in" }), when).toBeNull();
    };
    wait(300);
    expect(skeleton()).not.toBeNull();

    // The Portfolio's code at 350 ms, the empty hub list just after, Welcome's code 500 ms later.
    wait(50);
    await portfolio.arrive();
    await settle();
    held("once the hub list is empty");
    expect(router.state.navigation.location?.pathname).toBe("/welcome");
    for (let elapsed = 10; elapsed <= 500; elapsed += 10) {
      wait(10);
      held(`${String(elapsed)} ms after the Portfolio's code`);
    }
    await welcome.arrive();
    await settle();
    held("once Welcome's code is in");
    for (let elapsed = 10; elapsed <= 600 && !welcomed(); elapsed += 10) {
      wait(10);
      held(`${String(elapsed)} ms after Welcome's code`);
    }

    expect(welcomed()).toBe(true);
    expect(skeleton()).toBeNull();
    expect(router.state.location.pathname).toBe("/welcome");
  });

  it("ends on Welcome when the page under it redirects after the gate, on a slow first load", async () => {
    vi.useFakeTimers();
    stubNoHub();
    const sessions = heldModule({ SessionsListScreen: standIn("Sessions stand-in") });
    const welcome = heldModule({ WelcomeScreen: standIn("Welcome stand-in") });
    // As routes.tsx's /live: a page that only redirects, once its target's code is in.
    const router = openAt(
      gatedRoutes(
        [
          {
            path: "live",
            ...lazyRedirect(sessions.load, createElement(Redirect, { to: "/sessions" })),
          },
          { path: "sessions", ...lazyScreen(sessions.load, "SessionsListScreen") },
        ],
        welcome.load,
      ),
      "/live",
    );
    // The skeleton at 300 ms, /live's code at 350 ms, then the empty hub list, whose redirect makes
    // the shell's own skeleton due at 650 ms.
    wait(300);
    expect(skeleton()).not.toBeNull();
    wait(50);
    await sessions.arrive();
    await settle();
    expect(router.state.navigation.location?.pathname).toBe("/welcome");

    // Step by step, so the router can land between the timers: at 600 ms the first skeleton has
    // had its 300 ms, and /live's own redirect would be drawn.
    for (let elapsed = 10; elapsed <= 300; elapsed += 10) {
      wait(10);
      await settle();
    }
    await welcome.arrive();
    await settle();
    wait(1000);
    await settle();

    expect(router.state.location.pathname).toBe("/welcome");
    expect(screen.getByRole("heading", { level: 1, name: "Welcome stand-in" })).toBeInTheDocument();
  });

  it("ends on Welcome when another page opens while it waits for Welcome's code", async () => {
    vi.useFakeTimers();
    stubNoHub();
    const welcome = heldModule({ WelcomeScreen: standIn("Welcome stand-in") });
    const portfolio = { PortfolioScreen: standIn("Portfolio stand-in") };
    const sessions = { SessionsListScreen: standIn("Sessions stand-in") };
    const router = openAt(
      gatedRoutes(
        [
          { index: true, ...lazyScreen(() => Promise.resolve(portfolio), "PortfolioScreen") },
          {
            path: "sessions",
            ...lazyScreen(() => Promise.resolve(sessions), "SessionsListScreen"),
          },
        ],
        welcome.load,
      ),
      "/",
    );
    await settle();
    expect(router.state.navigation.location?.pathname).toBe("/welcome");

    // As a nav link would, before Welcome's code is in.
    act(() => {
      void router.navigate("/sessions");
    });
    await settle();
    await welcome.arrive();
    await settle();
    wait(1000);
    await settle();

    expect(router.state.location.pathname).toBe("/welcome");
    expect(screen.getByRole("heading", { level: 1, name: "Welcome stand-in" })).toBeInTheDocument();
  });
});

// Where each of routes.tsx's own redirects lands, with its target's route.
const LANDINGS: Record<string, { target: string; lands: string }> = {
  live: { target: "sessions", lands: "/sessions" },
  knowledge: { target: "knowledge/learnings", lands: "/knowledge/learnings" },
  settings: { target: "settings/:section", lands: "/settings/hubs" },
};

describe("the route table's redirects", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  /**
   * Opens `path` on `routes` on the fake clock, with the held route's code arriving once the
   * skeleton shows; returns the router. 300 ms later the skeleton has had its time, and the page,
   * a redirect here, is drawn.
   */
  async function openSlowly(held: HeldRoute, routes: RouteObject[], path: string) {
    vi.useFakeTimers();
    stubApi({ "/api/v1/projects": aPage([aProjectSummary()]) });
    stubEventSource();
    const router = openAt(routes, path);
    wait(300);
    expect(skeleton()).not.toBeNull();
    await held.arrive();
    return router;
  }

  it.each(OWN_REDIRECTS)(
    "keeps the page skeleton until /%s's target renders, on a slow first load",
    async (path) => {
      const landing = LANDINGS[path];
      if (landing === undefined) throw new Error(`no landing for /${path}`);
      const held = await heldRealRoute(path);
      const router = await openSlowly(
        held,
        shellRoutes([held.route, standInRoute(landing.target, "Target stand-in")]),
        `/${path}`,
      );

      // The redirect is drawn, and the router has yet to land.
      wait(300);
      expect(router.state.location.pathname).toBe(`/${path}`);
      expect(skeleton()).not.toBeNull();
      expect(main()).toHaveAttribute("aria-busy", "true");

      await settle();
      expect(router.state.location.pathname).toBe(landing.lands);
      expect(router.state.historyAction).toBe("REPLACE");
      expect(
        screen.getByRole("heading", { level: 1, name: "Target stand-in" }),
      ).toBeInTheDocument();
      expect(skeleton()).toBeNull();
    },
  );

  it("keeps the page skeleton until a Settings alias's section renders, on a slow first load", async () => {
    const held = await heldRealRoute("settings/:section");
    const router = await openSlowly(held, shellRoutes([held.route]), "/settings/retention");
    // The alias's section is on the same route, so the router lands at once: what main shows is
    // read as the router moves, before the section renders.
    const frames: string[] = [];
    const unsubscribe = router.subscribe((state) => {
      frames.push(`${state.location.pathname} ${skeleton() === null ? "empty" : "skeleton"}`);
    });

    wait(300);
    unsubscribe();
    expect(frames).toEqual(["/settings/privacy skeleton"]);
    expect(router.state.historyAction).toBe("REPLACE");
    await settle();
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  });
});
