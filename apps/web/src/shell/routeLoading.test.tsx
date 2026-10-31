import { act, fireEvent, render, screen, within } from "@testing-library/react";
import type { ComponentType } from "react";
import { createMemoryRouter, Link, Navigate, RouterProvider } from "react-router";
import type { RouteObject } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  aPage,
  aProjectSummary,
  stubApi,
  stubEventSource,
  testQueryClient,
  TestProviders,
} from "../testing/builders";
import { wholeText } from "../testing/text";
import { AppShell } from "./AppShell";
import { lazyRedirect, lazyScreen, RouteSkeleton } from "./routeLoading";

// Spec 22 and ux-change-route-loading.md: nothing new for 300 ms, then the page skeleton (held at
// least 300 ms), "Loading page" announced after 1 s, and a line under the skeleton after 10 s.
const STILL_LOADING = "Still loading this page. Check that hub web is still running.";

afterEach(() => {
  vi.useRealTimers();
});

function PortfolioStandIn() {
  return (
    <>
      <h1>Portfolio stand-in</h1>
      <Link to="/sessions">Open sessions</Link>
    </>
  );
}

function SessionsStandIn() {
  return <h1>Sessions stand-in</h1>;
}

function BrainPickerStandIn() {
  return <h1>Brain picker stand-in</h1>;
}

function BrainStandIn() {
  return <h1>Brain note stand-in</h1>;
}

/** A stand-in for the Sessions module's `import()`: it resolves only when the test calls `arrive`. */
function deferredSessions() {
  let resolve: (module: { SessionsListScreen: ComponentType }) => void = () => undefined;
  const loaded = new Promise<{ SessionsListScreen: ComponentType }>((done) => {
    resolve = done;
  });
  return {
    load: () => loaded,
    /** The module arrives, and the router takes it. */
    arrive: async () => {
      await act(async () => {
        resolve({ SessionsListScreen: SessionsStandIn });
        await loaded;
      });
    },
  };
}

type DeferredSessions = ReturnType<typeof deferredSessions>;

/** The app's route shape: the shell, then a pathless route whose fallback covers a first load. */
function shellRoutes(children: RouteObject[]): RouteObject[] {
  return [
    {
      element: <AppShell />,
      children: [{ hydrateFallbackElement: <RouteSkeleton />, children }],
    },
  ];
}

function sessionsRoutes(sessions: DeferredSessions): RouteObject[] {
  return shellRoutes([
    {
      index: true,
      ...lazyScreen(
        () => Promise.resolve({ PortfolioScreen: PortfolioStandIn }),
        "PortfolioScreen",
      ),
    },
    { path: "sessions", ...lazyScreen(sessions.load, "SessionsListScreen") },
  ]);
}

function renderAt(path: string, routes: RouteObject[]) {
  stubApi({ "/api/v1/projects": aPage([aProjectSummary()]) });
  stubEventSource();
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <TestProviders client={testQueryClient()}>
      <RouterProvider router={router} />
    </TestProviders>,
  );
  return router;
}

const main = () => screen.getByRole("main");
const skeleton = () => main().querySelector(".ah-skel");

/** Moves the fake clock by `ms`, then renders what its timers changed. */
function wait(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

type Entry = "an in-app navigation" | "a deep link";
const ENTRIES: Entry[] = ["an in-app navigation", "a deep link"];

/**
 * Starts loading /sessions on the fake clock, from the Portfolio stand-in's link or as the first
 * page, and returns the text `main` held just before the load began.
 */
async function startLoading(entry: Entry, sessions: DeferredSessions): Promise<string> {
  vi.useFakeTimers();
  if (entry === "a deep link") {
    renderAt("/sessions", sessionsRoutes(sessions));
    return "";
  }
  renderAt("/", sessionsRoutes(sessions));
  await act(async () => {
    await Promise.resolve();
  });
  expect(screen.getByRole("heading", { level: 1, name: "Portfolio stand-in" })).toBeInTheDocument();
  const before = main().textContent;
  fireEvent.click(screen.getByRole("link", { name: "Open sessions" }));
  return before;
}

describe("route loading", () => {
  it.each(ENTRIES)(
    "shows nothing new for 300 ms, then the page skeleton in main with aria-busy while a route's code loads (%s)",
    async (entry) => {
      const before = await startLoading(entry, deferredSessions());

      wait(299);
      expect(main().textContent).toBe(before);
      expect(skeleton()).toBeNull();
      expect(main()).not.toHaveAttribute("aria-busy", "true");

      wait(1);
      expect(skeleton()).not.toBeNull();
      expect(main()).toHaveAttribute("aria-busy", "true");
      expect(within(main()).queryByRole("heading", { name: "Portfolio stand-in" })).toBeNull();
    },
  );

  it("keeps the previous screen while the next screen's code loads for under 300 ms", async () => {
    const sessions = deferredSessions();
    await startLoading("an in-app navigation", sessions);

    wait(299);
    expect(
      screen.getByRole("heading", { level: 1, name: "Portfolio stand-in" }),
    ).toBeInTheDocument();
    expect(skeleton()).toBeNull();

    await sessions.arrive();
    expect(
      screen.getByRole("heading", { level: 1, name: "Sessions stand-in" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Portfolio stand-in" })).toBeNull();
    wait(1);
    expect(skeleton()).toBeNull();
    expect(main()).not.toHaveAttribute("aria-busy", "true");
  });

  it("keeps the previous screen and its address while a redirect's target code loads", async () => {
    vi.useFakeTimers();
    const sessions = deferredSessions();
    const router = renderAt(
      "/",
      shellRoutes([
        {
          index: true,
          ...lazyScreen(
            () => Promise.resolve({ PortfolioScreen: PortfolioStandIn }),
            "PortfolioScreen",
          ),
        },
        // As routes.tsx's /live: a bookmark that opens the Sessions screen, by a replace.
        { path: "live", ...lazyRedirect(sessions.load, <Navigate to="/sessions" replace />) },
        { path: "sessions", ...lazyScreen(sessions.load, "SessionsListScreen") },
      ]),
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(
      screen.getByRole("heading", { level: 1, name: "Portfolio stand-in" }),
    ).toBeInTheDocument();

    act(() => {
      void router.navigate("/live");
    });
    wait(299);
    expect(
      screen.getByRole("heading", { level: 1, name: "Portfolio stand-in" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");

    await sessions.arrive();
    await act(async () => {
      await Promise.resolve();
    });
    expect(
      screen.getByRole("heading", { level: 1, name: "Sessions stand-in" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sessions");
    expect(router.state.historyAction).toBe("REPLACE");
  });

  it.each(ENTRIES)("keeps the page skeleton at least 300 ms once shown (%s)", async (entry) => {
    const sessions = deferredSessions();
    await startLoading(entry, sessions);
    wait(300);
    expect(skeleton()).not.toBeNull();

    await sessions.arrive();
    wait(299);
    expect(skeleton()).not.toBeNull();
    expect(main()).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByRole("heading", { name: "Sessions stand-in" })).toBeNull();

    wait(1);
    expect(skeleton()).toBeNull();
    expect(
      screen.getByRole("heading", { level: 1, name: "Sessions stand-in" }),
    ).toBeInTheDocument();
  });

  it.each(ENTRIES)("announces Loading page only after 1 s (%s)", async (entry) => {
    await startLoading(entry, deferredSessions());

    wait(300);
    wait(699);
    expect(screen.queryByText(wholeText("Loading page"))).toBeNull();

    wait(1);
    const said = screen.getByText(wholeText("Loading page"));
    expect(said.closest("[role='status'], [aria-live='polite']")).not.toBeNull();
    // A screen reader may hold back what changes inside a busy element until it is no longer busy.
    expect(main()).toHaveAttribute("aria-busy", "true");
    expect(said.closest("[aria-busy='true']")).toBeNull();
  });

  it.each(ENTRIES)("says the page is still loading after 10 s (%s)", async (entry) => {
    await startLoading(entry, deferredSessions());

    wait(300);
    wait(700);
    wait(8999);
    expect(screen.queryByText(wholeText(STILL_LOADING))).toBeNull();

    wait(1);
    expect(within(main()).getByText(wholeText(STILL_LOADING))).toBeInTheDocument();
  });

  it("keeps the top bar and the nav mounted while a deep link's code loads", async () => {
    const sessions = deferredSessions();
    await startLoading("a deep link", sessions);
    const nav = screen.getByRole("navigation", { name: "Main" });
    const topBar = screen.getByRole("banner");

    wait(300);
    expect(screen.getByRole("navigation", { name: "Main" })).toBe(nav);
    expect(screen.getByRole("banner")).toBe(topBar);

    await sessions.arrive();
    wait(1000);
    expect(
      screen.getByRole("heading", { level: 1, name: "Sessions stand-in" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Main" })).toBe(nav);
    expect(screen.getByRole("banner")).toBe(topBar);
  });

  it("renders the screen and drops the skeleton once its code arrives", async () => {
    const sessions = deferredSessions();
    await startLoading("an in-app navigation", sessions);
    wait(300);
    wait(400);
    expect(skeleton()).not.toBeNull();

    await sessions.arrive();
    wait(0);
    expect(
      screen.getByRole("heading", { level: 1, name: "Sessions stand-in" }),
    ).toBeInTheDocument();
    expect(skeleton()).toBeNull();
    expect(main()).not.toHaveAttribute("aria-busy", "true");
  });

  it("loads the export the route names", async () => {
    // The picker comes first, as in screens/brain, so taking the first export would show it.
    const brainModule = { BrainPickerScreen: BrainPickerStandIn, BrainScreen: BrainStandIn };
    renderAt(
      "/projects/demo/brain/now.md",
      shellRoutes([
        {
          path: "projects/:project/brain/*",
          ...lazyScreen(() => Promise.resolve(brainModule), "BrainScreen"),
        },
      ]),
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "Brain note stand-in" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Brain picker stand-in" })).toBeNull();
  });
});
