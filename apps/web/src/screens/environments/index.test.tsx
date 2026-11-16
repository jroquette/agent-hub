import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement } from "react";
import { describe, expect, it } from "vitest";

import { environmentsLink } from "../../shell/Sidebar";
import { DiscussProvider } from "../../shell/discuss";
import { seriousViolations } from "../../testing/axe";
import { renderWithApi } from "../../testing/builders";
import type { ApiRoutes, RouteReply } from "../../testing/builders";
import { EnvironmentScreen } from "./EnvironmentPage";
import { EnvironmentsScreen } from "./index";

const CONFIG = "/api/v1/projects/demo/config";

/** The config fields the Environments page reads. */
function aConfig(environments: unknown[] = []) {
  return {
    project: "demo",
    local_file: { name: "hub.local.json", path: "/hubs/demo-hub/hub.local.json", problems: [] },
    repos: [{ dir: "demo-api", github: "acme/demo-api", role: "backend" }],
    environments: {
      environments,
      services: [],
      blocked_words: [],
      blocked_files: [],
      blocked_env: [],
    },
  };
}

const WRITE = "POST /api/v1/projects/demo/config/environments";

function open(config: unknown = aConfig(), routes: ApiRoutes = {}) {
  return renderWithApi(createElement(DiscussProvider, null, createElement(EnvironmentsScreen)), {
    routes: { [CONFIG]: config as RouteReply, ...routes },
    path: "/projects/demo/environments",
    route: "projects/:project/environments",
  });
}

/** One environment's own page, where its services' panels open. */
function openEnvironment(name: string, config: unknown, routes: ApiRoutes = {}) {
  return renderWithApi(createElement(DiscussProvider, null, createElement(EnvironmentScreen)), {
    routes: { [CONFIG]: config as RouteReply, ...routes },
    path: `/projects/demo/environment/${name}`,
    route: "projects/:project/environment/:name",
  });
}

function environment(name: string, access: string, source: string, extra = {}) {
  return {
    name,
    access,
    production: false,
    description: null,
    credentials: null,
    source,
    team_access: source === "hub.json" ? access : null,
    ...extra,
  };
}

/** Two team environments (one production), one tightened, one of mine; one service. */
function withEnvironments() {
  const config = aConfig([
    environment("local", "write", "hub.json", { description: "docker compose stack" }),
    environment("live", "read", "hub.json", {
      production: true,
      credentials: { aws_profile: "demo-live-ro", env: ["DEMO_LIVE_DB_URL"] },
    }),
    environment("staging", "read", "hub.local.json", { team_access: "write" }),
    environment("jane-cloud", "write", "hub.local.json"),
  ]);
  config.repos.push({ dir: "demo-web", github: "acme/demo-web", role: "frontend" });
  config.environments.services = [
    {
      repo: "demo-api",
      name: "api",
      kind: "api",
      description: null,
      endpoints: [
        { environment: "local", endpoint: { url: "http://localhost:8000" }, source: "hub.json" },
        {
          environment: "jane-cloud",
          endpoint: { url: "https://api.jane.example.com" },
          source: "hub.local.json",
        },
      ],
    },
  ] as never[];
  return config;
}

/** A discovery as the list answers it; only the fields the banner reads matter. */
function aDiscovery(state: string, proposal: unknown = null) {
  return {
    id: "abc123abc123",
    project: "demo",
    agent_session_id: "as-1",
    repos: ["demo-api"],
    environments: [],
    suggest_environments: true,
    created_at: "2026-10-20T10:00:00Z",
    state,
    problem: null,
    proposal,
  };
}

describe("EnvironmentsScreen", () => {
  it("AC-417.3 lists the project's environments on their own page", async () => {
    open(
      aConfig([
        {
          name: "staging",
          access: "ask",
          production: false,
          description: "Shared test environment",
          credentials: null,
          source: "hub.json",
          team_access: "ask",
        },
      ]),
    );

    expect(await screen.findByRole("heading", { level: 1, name: "Environments" })).toBeVisible();
    const section = await screen.findByRole("region", { name: /Environments/ });
    expect(within(section).getByText("Agents ask before writing")).toBeVisible();
    expect(within(section).getByText("Shared test environment")).toBeVisible();
    expect(within(section).getByRole("link", { name: "staging" })).toBeVisible();
    expect(
      within(section).getByRole("button", { name: "Remove environment staging" }),
    ).toBeVisible();
  });

  it("AC-417.17 opens the add flow so it comes back to this page", async () => {
    const { router } = open();

    await userEvent.click(await screen.findByRole("button", { name: "Add environment" }));

    expect(router.state.location.pathname).toBe("/projects/demo/environments/new");
    expect(router.state.location.state).toEqual({
      returnTo: "/projects/demo/environments",
      returnLabel: "Environments",
    });
  });

  it("AC-417.3 lays environments out as a table: access, secrets and who set them", async () => {
    open(withEnvironments());

    const table = await screen.findByRole("table", { name: "Environments and what agents may do" });
    expect(within(table).getAllByText("Agents may change data")).toHaveLength(2);
    expect(within(table).getAllByText("Agents only read")).toHaveLength(2);
    expect(within(table).getByText("Production")).toBeVisible();
    expect(within(table).getByText("Tightened by you")).toBeVisible();
    expect(within(table).getByText("Team: may change data")).toBeVisible();
    expect(within(table).getByText("demo-live-ro")).toBeVisible();
    expect(within(table).getByText("DEMO_LIVE_DB_URL")).toBeVisible();
  });

  it("AC-417.3 counts each environment's services and leaves their addresses to its own page", async () => {
    open(withEnvironments());

    const table = await screen.findByRole("table", { name: "Environments and what agents may do" });
    expect(within(table).getAllByText("1 service")).toHaveLength(2);
    expect(within(table).getAllByText("None yet").length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("table", { name: "Addresses per service and environment" }),
    ).not.toBeInTheDocument();
  });

  it("AC-417.4 opens an environment's page from its name and from anywhere on its row", async () => {
    const { router } = open(withEnvironments());

    const table = await screen.findByRole("table", { name: "Environments and what agents may do" });
    expect(within(table).getByRole("link", { name: "live" })).toHaveAttribute(
      "href",
      "/projects/demo/environment/live",
    );
    await userEvent.click(within(table).getByText("demo-live-ro"));

    expect(router.state.location.pathname).toBe("/projects/demo/environment/live");
  });

  it("AC-417.4 keeps the row's own buttons from opening the environment", async () => {
    const { router } = open(withEnvironments());

    await userEvent.click(
      await screen.findByRole("button", { name: "Remove environment jane-cloud" }),
    );

    expect(screen.getByRole("alertdialog")).toBeVisible();
    expect(router.state.location.pathname).toBe("/projects/demo/environments");
  });
  it("AC-417.5 removes an environment in use and its addresses in one confirmed write", async () => {
    const { requests } = open(withEnvironments(), { [WRITE]: withEnvironments() });

    await userEvent.click(
      await screen.findByRole("button", { name: "Remove environment jane-cloud" }),
    );
    const dialog = screen.getByRole("alertdialog", {
      name: "Remove jane-cloud and its 1 address?",
    });
    expect(within(dialog).getByText(/demo-api › api/)).toBeVisible();
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Remove environment and 1 address" }),
    );

    expect(await screen.findByText("Removed jane-cloud")).toBeVisible();
    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({
      op: "batch",
      ops: [
        {
          op: "remove_endpoint",
          scope: "local",
          repo: "demo-api",
          service: "api",
          environment: "jane-cloud",
        },
        { op: "remove_environment", scope: "local", name: "jane-cloud" },
      ],
    });
  });
  it("AC-417.5 confirms before going back to the team's looser access", async () => {
    const { requests } = open(withEnvironments(), { [WRITE]: withEnvironments() });

    await userEvent.click(
      await screen.findByRole("button", { name: "Use the team's access for staging" }),
    );
    const dialog = screen.getByRole("alertdialog", { name: "Use the team's access for staging?" });
    expect(requests.some((r) => r.method === "POST")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Use the team's access" }));

    expect(await screen.findByText("staging is back to the team's access")).toBeVisible();
    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({
      op: "remove_environment",
      scope: "local",
      name: "staging",
    });
  });

  it("AC-417.8 changes a service's addresses together in its panel", async () => {
    const { requests } = openEnvironment("local", withEnvironments(), {
      [WRITE]: withEnvironments(),
    });

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Open demo-api › api: http://localhost:8000 in local",
      }),
    );
    const panel = screen.getByRole("complementary", { name: "demo-api › api" });
    expect(within(panel).getByRole("textbox", { name: "Address in local" })).toHaveFocus();
    await userEvent.type(
      within(panel).getByRole("textbox", { name: "Address in live" }),
      "https://api.example.com",
    );
    await userEvent.click(
      within(panel).getByRole("button", { name: "Remove the jane-cloud address" }),
    );
    expect(within(panel).getByText("Removed on save")).toBeVisible();
    expect(requests.some((r) => r.method === "POST")).toBe(false);
    await userEvent.click(within(panel).getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("Saved 2 addresses of demo-api › api")).toBeVisible();
    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({
      op: "batch",
      ops: [
        {
          op: "add_endpoint",
          scope: "team",
          repo: "demo-api",
          service: "api",
          environment: "live",
          url: "https://api.example.com",
          resource: null,
          note: null,
          replace: false,
        },
        {
          op: "remove_endpoint",
          scope: "local",
          repo: "demo-api",
          service: "api",
          environment: "jane-cloud",
        },
      ],
    });
  });

  it("AC-417.8 asks before closing a panel with unsaved changes", async () => {
    openEnvironment("local", withEnvironments());

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Open demo-api › api: http://localhost:8000 in local",
      }),
    );
    const panel = screen.getByRole("complementary", { name: "demo-api › api" });
    await userEvent.type(
      within(panel).getByRole("textbox", { name: "Address in live" }),
      "orders-table",
    );
    await userEvent.click(within(panel).getByRole("button", { name: "Close demo-api › api" }));

    expect(screen.getByRole("alertdialog", { name: "Discard 1 change?" })).toBeVisible();
  });
  it("AC-418.14 leads back to a search Claude is still running", async () => {
    const { router } = open(aConfig(), {
      "/api/v1/projects/demo/environment-discoveries": {
        items: [aDiscovery("running")],
        total_estimate: 1,
      },
    });

    expect(await screen.findByText("Claude is reading the repos for services.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Open progress" }));

    expect(router.state.location.pathname).toBe("/projects/demo/environments/discover");
    expect(router.state.location.search).toBe("?discovery=abc123abc123");
  });

  it("AC-418.14 offers the review of a finished search", async () => {
    const { router } = open(aConfig(), {
      "/api/v1/projects/demo/environment-discoveries": {
        items: [aDiscovery("finished", { environments: [{}], services: [{}, {}] })],
        total_estimate: 1,
      },
    });

    expect(await screen.findByText("Claude found 3 items in the repos.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Review 3 proposals" }));

    expect(router.state.location.pathname).toBe(
      "/projects/demo/environments/discover/abc123abc123",
    );
  });

  it("AC-418.14 shows no banner for a stopped search", async () => {
    open(aConfig(), {
      "/api/v1/projects/demo/environment-discoveries": {
        items: [aDiscovery("stopped")],
        total_estimate: 1,
      },
    });

    await screen.findByRole("heading", { level: 1, name: "Environments" });
    expect(screen.queryByText(/Claude is reading the repos/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Review/ })).toBeNull();
  });

  it("has no serious a11y violations", async () => {
    const { container } = open();
    await screen.findByRole("heading", { level: 1, name: "Environments" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("environmentsLink", () => {
  it("AC-417.2 follows the open project, then the one in scope, else the picker", () => {
    expect(environmentsLink("demo", "other")).toBe("/projects/demo/environments");
    expect(environmentsLink(null, "other")).toBe("/projects/other/environments");
    expect(environmentsLink(null, null)).toBe("/environments");
  });
});
