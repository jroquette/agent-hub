import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement } from "react";
import { describe, expect, it } from "vitest";

import { environmentsLink } from "../../shell/Sidebar";
import { DiscussProvider } from "../../shell/discuss";
import { seriousViolations } from "../../testing/axe";
import { renderWithApi } from "../../testing/builders";
import type { ApiRoutes, RouteReply } from "../../testing/builders";
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

describe("EnvironmentsScreen", () => {
  it("lists the project's environments on their own page", async () => {
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
    expect(within(section).getByRole("button", { name: "Edit: staging" })).toBeVisible();
    expect(
      within(section).getByRole("button", { name: "Remove environment staging" }),
    ).toBeVisible();
  });

  it("opens the add flow so it comes back to this page", async () => {
    const { router } = open();

    await userEvent.click(await screen.findByRole("button", { name: "Add environment" }));

    expect(router.state.location.pathname).toBe("/projects/demo/environments/new");
    expect(router.state.location.state).toEqual({
      returnTo: "/projects/demo/environments",
      returnLabel: "Environments",
    });
  });

  it("lays environments out as a table: access, secrets and who set them", async () => {
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

  it("shows each service's address per environment, and repos with none", async () => {
    open(withEnvironments());

    const matrix = await screen.findByRole("table", {
      name: "Addresses per service and environment",
    });
    expect(
      within(matrix).getByRole("button", {
        name: "Edit the address of demo-api › api in local: http://localhost:8000",
      }),
    ).toBeVisible();
    expect(
      within(matrix).getByRole("button", { name: "Add address for demo-api › api in live" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Add a service to demo-web" })).toBeVisible();
  });

  it("opens an environment's page from its name and from Edit", async () => {
    const { router } = open(withEnvironments());

    const table = await screen.findByRole("table", { name: "Environments and what agents may do" });
    expect(within(table).getByRole("link", { name: /^live/ })).toHaveAttribute(
      "href",
      "/projects/demo/environment/live",
    );
    await userEvent.click(within(table).getByRole("button", { name: "Edit: live" }));

    expect(router.state.location.pathname).toBe("/projects/demo/environment/live");
  });
  it("removes an environment in use and its addresses in one confirmed write", async () => {
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
  it("confirms before going back to the team's looser access", async () => {
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

  it("changes a service's addresses together in its panel", async () => {
    const { requests } = open(withEnvironments(), { [WRITE]: withEnvironments() });

    await userEvent.click(
      await screen.findByRole("button", {
        name: /Edit the address of demo-api › api in local/,
      }),
    );
    const panel = screen.getByRole("dialog", { name: "demo-api › api" });
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

  it("asks before closing a panel with unsaved changes", async () => {
    open(withEnvironments());

    await userEvent.click(await screen.findByRole("button", { name: "Open demo-api › api" }));
    const panel = screen.getByRole("dialog", { name: "demo-api › api" });
    await userEvent.type(
      within(panel).getByRole("textbox", { name: "Address in live" }),
      "orders-table",
    );
    await userEvent.click(within(panel).getByRole("button", { name: "Close demo-api › api" }));

    expect(screen.getByRole("alertdialog", { name: "Discard 1 change?" })).toBeVisible();
  });
  it("has no serious a11y violations", async () => {
    const { container } = open();
    await screen.findByRole("heading", { level: 1, name: "Environments" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("environmentsLink", () => {
  it("follows the open project, then the one in scope, else the picker", () => {
    expect(environmentsLink("demo", "other")).toBe("/projects/demo/environments");
    expect(environmentsLink(null, "other")).toBe("/projects/other/environments");
    expect(environmentsLink(null, null)).toBe("/environments");
  });
});
