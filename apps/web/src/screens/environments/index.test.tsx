import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement } from "react";
import { describe, expect, it } from "vitest";

import { environmentsLink } from "../../shell/Sidebar";
import { DiscussProvider } from "../../shell/discuss";
import { seriousViolations } from "../../testing/axe";
import { renderWithApi } from "../../testing/builders";
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

function open(config: ReturnType<typeof aConfig> = aConfig()) {
  return renderWithApi(createElement(DiscussProvider, null, createElement(EnvironmentsScreen)), {
    routes: { [CONFIG]: config },
    path: "/projects/demo/environments",
    route: "projects/:project/environments",
  });
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
