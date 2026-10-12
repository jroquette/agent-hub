import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";

import { App } from "./App";
import { appRoutes } from "./routes";
import { seriousViolations } from "./testing/axe";
import {
  aFeatureDetail,
  aHub,
  aPage,
  stubApi,
  stubEventSource,
  testQueryClient,
  TestProviders,
  type ApiRoutes,
} from "./testing/builders";

const withHub: ApiRoutes = {
  "/api/v1/hubs": aPage([aHub()]),
  "/api/v1/projects": aPage([]),
  "/api/v1/features/agent-hub/control-plane": aFeatureDetail(),
};
const noHub: ApiRoutes = { "/api/v1/hubs": aPage([]), "/api/v1/projects": aPage([]) };

function renderAt(path: string, routes: ApiRoutes) {
  stubApi(routes);
  stubEventSource();
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] });
  const result = render(
    <TestProviders client={testQueryClient()}>
      <RouterProvider router={router} />
    </TestProviders>,
  );
  return { ...result, router };
}

describe("routes", () => {
  it.each([
    ["/", "Portfolio"],
    ["/projects/agent-hub", "Project not found"],
    ["/approvals", "Approvals"],
    ["/approvals/abc", "Approvals"],
    ["/live", "Live sessions"],
    ["/sessions", "Sessions"],
    ["/sessions/abc", "Session detail"],
    ["/runs", "Workflow runs"],
    ["/runs/abc", "Run abc not found"],
    ["/knowledge/learnings", "Knowledge"],
    ["/knowledge/brain", "Brain"],
    ["/knowledge/decisions", "Decisions"],
    ["/knowledge/context", "Context"],
    ["/features", "Features"],
    ["/features/agent-hub/control-plane", "control-plane"],
    ["/health", "Health"],
    ["/settings/hubs", "Settings"],
    ["/welcome", "Set up agent-hub on this machine"],
    ["/metrics", "This page does not exist"],
  ])("opens %s on the %s screen when a hub is registered", async (path, title) => {
    renderAt(path, withHub);

    expect(await screen.findByRole("heading", { level: 1, name: title })).toBeInTheDocument();
  });

  it.each([
    ["/knowledge", "/knowledge/learnings"],
    ["/settings", "/settings/hubs"],
  ])("redirects %s to %s", async (from, to) => {
    const { router } = renderAt(from, withHub);

    await screen.findByRole("heading", { level: 1 });
    expect(router.state.location.pathname).toBe(to);
  });

  it("redirects to welcome when no hub is registered", async () => {
    const { router } = renderAt("/sessions", noHub);

    expect(
      await screen.findByRole("heading", { level: 1, name: "Set up agent-hub on this machine" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/welcome");
  });

  it("keeps settings open when no hub is registered", async () => {
    const { router } = renderAt("/settings/hubs", noHub);

    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/settings/hubs");
  });

  it("stays on the page when the hub list cannot be read", async () => {
    const { router } = renderAt("/sessions", { "/api/v1/projects": aPage([]) });

    expect(await screen.findByRole("heading", { level: 1, name: "Sessions" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sessions");
  });

  it("has no serious or critical a11y violation on the shell", async () => {
    const { container } = renderAt("/", withHub);
    await screen.findByRole("heading", { level: 1, name: "Portfolio" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("App", () => {
  it("renders the shell in the browser router", async () => {
    stubApi(withHub);
    stubEventSource();
    render(<App />);

    expect(await screen.findByRole("navigation", { name: "Main" })).toBeInTheDocument();
  });
});
