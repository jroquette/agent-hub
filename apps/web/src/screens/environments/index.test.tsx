import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement } from "react";
import { describe, expect, it } from "vitest";

import { environmentsLink } from "../../shell/Sidebar";
import { DiscussProvider } from "../../shell/discuss";
import { seriousViolations } from "../../testing/axe";
import { aProblem, renderWithApi } from "../../testing/builders";
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

  it("shows a refused access under its field", async () => {
    open(withEnvironments(), {
      [WRITE]: aProblem({
        status: 422,
        title: "This change was not saved",
        errors: [
          {
            pointer: "environments.live.access",
            message: "hub.local.json: may only tighten hub.json's read",
          },
        ],
      }),
    });

    await userEvent.click(await screen.findByRole("button", { name: "Edit: live" }));
    const dialog = screen.getByRole("dialog", { name: "Edit environment live" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Save for the team" }));

    expect(await within(dialog).findByText("May only tighten hub.json's read")).toBeVisible();
  });

  it("asks to remove the addresses of an environment still in use first", async () => {
    open(withEnvironments());

    await userEvent.click(
      await screen.findByRole("button", { name: "Remove environment jane-cloud" }),
    );

    const dialog = screen.getByRole("dialog", { name: /jane-cloud is still used by 1 address$/ });
    expect(within(dialog).getByText(/demo-api › api/)).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Remove 1 address" })).toBeVisible();
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

  it("confirms before removing an address", async () => {
    const { requests } = open(withEnvironments());

    await userEvent.click(
      await screen.findByRole("button", {
        name: /Edit the address of demo-api › api in local/,
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Remove address" }));

    const dialog = screen.getByRole("alertdialog", {
      name: "Remove the local address of demo-api › api?",
    });
    expect(within(dialog).getByText(/hub.json changes/)).toBeVisible();
    expect(requests.some((r) => r.method === "POST")).toBe(false);
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
