import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentType } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import type { RouteObject } from "react-router";
import { describe, expect, it, onTestFinished, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
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
import { RouteError } from "./RouteError";
import { lazyScreen, RouteSkeleton } from "./routeLoading";

const CHUNK_URL = "http://127.0.0.1:7420/assets/sessions-list-3f2a9c.js";
// What each browser's import() rejects with (a TypeError) when it cannot fetch a chunk.
const CHROMIUM = `Failed to fetch dynamically imported module: ${CHUNK_URL}`;
const FIREFOX = `error loading dynamically imported module: ${CHUNK_URL}`;
const SAFARI = "Importing a module script failed.";
const BROWSER_ERRORS: [string, string][] = [
  ["Chromium", CHROMIUM],
  ["Firefox", FIREFOX],
  ["Safari", SAFARI],
];
const DRAWING_ERROR = "Cannot read properties of undefined (reading 'items')";

function HealthStandIn() {
  return <h1>Health stand-in</h1>;
}

/** The Sessions route, whose import() rejects as a browser's does when the chunk cannot load. */
function failingSessions(message: string): RouteObject {
  return {
    path: "sessions",
    ...lazyScreen(() => Promise.reject(new TypeError(message)), "SessionsListScreen"),
  };
}

/** The Sessions route, whose code loads but whose screen throws `error` while rendering. */
function throwingSessions(error: Error): RouteObject {
  const sessionsModule: { SessionsListScreen: ComponentType } = {
    SessionsListScreen: () => {
      throw error;
    },
  };
  return {
    path: "sessions",
    ...lazyScreen(() => Promise.resolve(sessionsModule), "SessionsListScreen"),
  };
}

/** The app's route shape: the shell, then a pathless route holding the route error and fallback. */
function renderAt(path: string, sessions: RouteObject) {
  stubApi({ "/api/v1/projects": aPage([aProjectSummary()]) });
  stubEventSource();
  const health: RouteObject = {
    path: "health",
    ...lazyScreen(() => Promise.resolve({ HealthScreen: HealthStandIn }), "HealthScreen"),
  };
  const router = createMemoryRouter(
    [
      {
        element: <AppShell />,
        children: [
          {
            errorElement: <RouteError />,
            hydrateFallbackElement: <RouteSkeleton />,
            children: [sessions, health],
          },
        ],
      },
    ],
    { initialEntries: [path] },
  );
  const view = render(
    <TestProviders client={testQueryClient()}>
      <RouterProvider router={router} />
    </TestProviders>,
  );
  return { ...view, router };
}

/** Puts a stand-in for the browser's location in place: jsdom cannot reload a page. */
function stubLocationReload() {
  const reload = vi.fn();
  const { hash, host, hostname, href, origin, pathname, port, protocol, search } = window.location;
  vi.stubGlobal("location", {
    hash,
    host,
    hostname,
    href,
    origin,
    pathname,
    port,
    protocol,
    search,
    toString: () => href,
    reload,
  });
  onTestFinished(() => {
    vi.unstubAllGlobals();
  });
  return reload;
}

describe("RouteError", () => {
  it.each(BROWSER_ERRORS)(
    "says the page could not load, with Reload page and Go to Portfolio, when a route's code fails (%s)",
    async (_browser, message) => {
      renderAt("/sessions", failingSessions(message));

      const heading = await screen.findByRole("heading", {
        level: 1,
        name: "This page could not load",
      });
      const main = screen.getByRole("main");
      expect(main).toContainElement(heading);
      const alert = within(main).getByRole("alert");
      expect(alert).toContainElement(heading);
      expect(
        within(alert).getByText(wholeText("The app could not fetch this page from hub web.")),
      ).toBeInTheDocument();
      expect(within(main).getByText(wholeText("Page did not load"))).toBeInTheDocument();
      expect(
        within(main).getByText(
          wholeText(
            "The app may have been updated since this tab opened, or hub web stopped. Reloading gets the current version.",
          ),
        ),
      ).toBeInTheDocument();
      expect(within(main).getByRole("button", { name: "Reload page" })).toBeInTheDocument();
      expect(within(main).getByRole("link", { name: "Go to Portfolio" })).toHaveAttribute(
        "href",
        "/",
      );
      expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
      expect(screen.getByRole("banner")).toBeInTheDocument();
    },
  );

  it("reloads the page when Reload page is pressed", async () => {
    const reload = stubLocationReload();
    renderAt("/sessions", failingSessions(CHROMIUM));
    const button = await screen.findByRole("button", { name: "Reload page" });
    expect(reload).not.toHaveBeenCalled();

    await userEvent.click(button);

    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("says the page could not be shown when a screen throws while rendering", async () => {
    renderAt("/sessions", throwingSessions(new TypeError(DRAWING_ERROR)));

    const heading = await screen.findByRole("heading", {
      level: 1,
      name: "This page could not be shown",
    });
    const main = screen.getByRole("main");
    expect(within(main).getByRole("alert")).toContainElement(heading);
    expect(within(main).getByText(wholeText("Page error"))).toBeInTheDocument();
    expect(
      within(main).getByText(wholeText(`It failed while drawing: ${DRAWING_ERROR}.`)),
    ).toBeInTheDocument();
    expect(
      within(main).getByText(wholeText("Other pages still work. Reload the page to try again.")),
    ).toBeInTheDocument();
    expect(within(main).getByRole("button", { name: "Reload page" })).toBeInTheDocument();
    expect(within(main).getByRole("link", { name: "Go to Portfolio" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
  });

  it("shows at most 200 characters of the error's first line", async () => {
    const kept = `<b>bold</b> ${"x".repeat(188)}`;
    expect(kept).toHaveLength(200);
    const message = `${kept}BEYOND${"y".repeat(44)}\n    at SessionsListScreen (index.tsx:12:5)`;
    renderAt("/sessions", throwingSessions(new Error(message)));

    await screen.findByRole("heading", { level: 1, name: "This page could not be shown" });
    const main = screen.getByRole("main");
    expect(
      within(main).getByText(wholeText(`It failed while drawing: ${kept}.`)),
    ).toBeInTheDocument();
    expect(main).not.toHaveTextContent("BEYOND");
    expect(main).not.toHaveTextContent("at SessionsListScreen");
    expect(within(main).queryByText("bold", { selector: "b" })).toBeNull();
  });

  it.each([
    ["Chromium", CHROMIUM, "Requested: /sessions?view=grid · file assets/sessions-list-3f2a9c.js"],
    ["Firefox", FIREFOX, "Requested: /sessions?view=grid · file assets/sessions-list-3f2a9c.js"],
    ["Safari", SAFARI, "Requested: /sessions?view=grid"],
  ])(
    "names the requested path and the chunk file when the error names one (%s)",
    async (_browser, message, line) => {
      renderAt("/sessions?view=grid", failingSessions(message));

      await screen.findByRole("heading", { level: 1, name: "This page could not load" });
      const main = screen.getByRole("main");
      expect(within(main).getByText(wholeText(line))).toBeInTheDocument();
      expect(main.textContent.includes(" · file ")).toBe(line.includes(" · file "));
    },
  );

  it("opens another route from the nav after a route's code failed", async () => {
    const { router } = renderAt("/sessions", failingSessions(CHROMIUM));
    await screen.findByRole("heading", { level: 1, name: "This page could not load" });

    await userEvent.click(
      within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", {
        name: "Health",
      }),
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "Health stand-in" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "This page could not load" })).toBeNull();
    expect(router.state.location.pathname).toBe("/health");
  });

  it("has no serious a11y violations on both variants (a11y)", async () => {
    const code = renderAt("/sessions", failingSessions(CHROMIUM));
    await screen.findByRole("heading", { level: 1, name: "This page could not load" });
    expect(await seriousViolations(code.container)).toEqual([]);
    code.unmount();

    const drawing = renderAt("/sessions", throwingSessions(new TypeError(DRAWING_ERROR)));
    await screen.findByRole("heading", { level: 1, name: "This page could not be shown" });
    expect(await seriousViolations(drawing.container)).toEqual([]);
  });
});
