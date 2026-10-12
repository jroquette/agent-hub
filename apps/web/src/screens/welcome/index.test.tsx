import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";

import { appRoutes } from "../../routes";
import { seriousViolations } from "../../testing/axe";
import {
  aCollectorStatus,
  aHub,
  aPage,
  aProblem,
  aSession,
  aSettings,
  renderWithApi,
  stubApi,
  stubEventSource,
  testQueryClient,
  TestProviders,
  type ApiRoutes,
} from "../../testing/builders";
import { WelcomeScreen } from "./index";

const fresh: ApiRoutes = {
  "/api/v1/hubs": aPage([]),
  "/api/v1/collector/status": aCollectorStatus(),
  "/api/v1/settings": aSettings(),
  "/api/v1/sessions": aPage([]),
};

function step(name: string): HTMLElement {
  const item = screen.getByRole("heading", { name }).closest("li");
  if (!item) throw new Error(`No step ${name}`);
  return item;
}

describe("WelcomeScreen", () => {
  it("lists the three steps with the D27 copy", async () => {
    renderWithApi(<WelcomeScreen />, { routes: fresh, path: "/welcome" });

    expect(
      screen.getByRole("heading", { level: 1, name: "Set up agent-hub on this machine" }),
    ).toBeInTheDocument();
    const names = within(screen.getByRole("list", { name: "Setup steps" }))
      .getAllByRole("heading")
      .map((h) => h.textContent);
    expect(names).toEqual([
      "Register your hub",
      "Keep hub web running",
      "Start a Claude Code session in the hub",
    ]);
    expect(await within(step("Register your hub")).findByText("To do")).toBeInTheDocument();
  });

  it("marks Keep hub web running done while the API answers", async () => {
    renderWithApi(<WelcomeScreen />, { routes: fresh, path: "/welcome" });

    const running = step("Keep hub web running");
    expect(await within(running).findByText("Done")).toBeInTheDocument();
    expect(running).toHaveTextContent(
      "agent-hub is running at 127.0.0.1:7420 · db /home/dev/.local/share/agent-hub/events.db",
    );
  });

  it("shows the start command when the API does not answer", async () => {
    renderWithApi(<WelcomeScreen />, {
      routes: { ...fresh, "/api/v1/collector/status": aProblem({ status: 503, title: "Busy" }) },
      path: "/welcome",
    });

    const running = step("Keep hub web running");
    expect(await within(running).findByText(/not yet/)).toBeInTheDocument();
    expect(within(running).getByText("hub web")).toBeInTheDocument();
  });

  it("registers a hub from the form and shows what it detected", async () => {
    let hubs = aPage<ReturnType<typeof aHub>>([]);
    const { requests } = renderWithApi(<WelcomeScreen />, {
      routes: {
        ...fresh,
        "/api/v1/hubs": () => hubs,
        "POST /api/v1/hubs": () => {
          hubs = aPage([aHub({ lock_version: "0.3.0", lock_state: "drift" })]);
          return hubs.items[0];
        },
      },
      path: "/welcome",
    });

    await userEvent.type(screen.getByLabelText("Hub path"), "/home/dev/agent-hub-hub");
    await userEvent.click(screen.getByRole("button", { name: "Register hub" }));

    const register = step("Register your hub");
    expect(await within(register).findByText("Done")).toBeInTheDocument();
    expect(register).toHaveTextContent(
      "/home/dev/agent-hub-hub · agent-hub · platform 0.4.0 pinned, 0.3.0 synced (sync pending)",
    );
    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({ path: "/home/dev/agent-hub-hub" });
  });

  it("shows the problem under the input when registering fails", async () => {
    renderWithApi(<WelcomeScreen />, {
      routes: {
        ...fresh,
        "POST /api/v1/hubs": aProblem({
          status: 422,
          title: "No hub.json",
          detail: "No hub.json in /home/dev/agent-hub.",
        }),
      },
      path: "/welcome",
    });

    await userEvent.type(screen.getByLabelText("Hub path"), "/home/dev/agent-hub");
    await userEvent.click(screen.getByRole("button", { name: "Register hub" }));

    expect(await screen.findByText("No hub.json in /home/dev/agent-hub.")).toBeInTheDocument();
    expect(screen.getByLabelText("Hub path")).toHaveValue("/home/dev/agent-hub");
    expect(screen.getByLabelText("Hub path")).toHaveAttribute("aria-invalid", "true");
  });

  it("finishes when a session from a registered hub is seen", async () => {
    renderWithApi(<WelcomeScreen />, {
      routes: {
        ...fresh,
        "/api/v1/hubs": aPage([aHub()]),
        "/api/v1/sessions": aPage([aSession()]),
      },
      path: "/welcome",
    });

    expect(
      await screen.findByRole("heading", { level: 1, name: "You are set up" }),
    ).toBeInTheDocument();
    expect(step("Start a Claude Code session in the hub")).toHaveTextContent(
      "Session 5091b986 started",
    );
    expect(screen.getByRole("button", { name: /Go to Portfolio/ })).toBeEnabled();
  });

  it("keeps Go to Portfolio disabled until the steps are done (states)", async () => {
    renderWithApi(<WelcomeScreen />, { routes: fresh, path: "/welcome" });

    await within(step("Keep hub web running")).findByText("Done");
    expect(screen.getByRole("button", { name: /Go to Portfolio/ })).toBeDisabled();
    expect(step("Start a Claude Code session in the hub")).toHaveTextContent(
      "cd <path-to-your-hub> && claude",
    );
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = renderWithApi(<WelcomeScreen />, { routes: fresh, path: "/welcome" });
    await within(step("Keep hub web running")).findByText("Done");

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("welcome redirect", () => {
  function renderAt(path: string, routes: ApiRoutes) {
    stubApi(routes);
    stubEventSource();
    const router = createMemoryRouter(appRoutes, { initialEntries: [path] });
    render(
      <TestProviders client={testQueryClient()}>
        <RouterProvider router={router} />
      </TestProviders>,
    );
    return router;
  }

  it.each(["/", "/sessions", "/health"])(
    "redirects %s to the welcome page when no hub is registered",
    async (path) => {
      const router = renderAt(path, { ...fresh, "/api/v1/projects": aPage([]) });

      expect(
        await screen.findByRole("heading", { level: 1, name: "Set up agent-hub on this machine" }),
      ).toBeInTheDocument();
      expect(router.state.location.pathname).toBe("/welcome");
    },
  );

  it("keeps settings open when no hub is registered", async () => {
    const router = renderAt("/settings/hubs", fresh);

    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/settings/hubs");
  });
});
