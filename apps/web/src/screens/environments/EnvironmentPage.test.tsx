import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement } from "react";
import { describe, expect, it } from "vitest";

import { DiscussProvider } from "../../shell/discuss";
import { seriousViolations } from "../../testing/axe";
import { aProblem, renderWithApi } from "../../testing/builders";
import type { ApiRoutes, RouteReply } from "../../testing/builders";
import { EnvironmentScreen } from "./EnvironmentPage";

const CONFIG = "/api/v1/projects/demo/config";
const WRITE = "POST /api/v1/projects/demo/config/environments";

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

/** A team staging, a team live tightened by me, one service with a staging address. */
function aConfig() {
  return {
    project: "demo",
    local_file: { name: "hub.local.json", path: "/hubs/demo-hub/hub.local.json", problems: [] },
    repos: [{ dir: "demo-api", github: "acme/demo-api", role: "backend" }],
    environments: {
      environments: [
        environment("staging", "ask", "hub.json", {
          description: "Shared test environment",
          credentials: { aws_profile: "demo-staging", env: null, env_file: null },
        }),
        environment("live", "read", "hub.local.json", { team_access: "write", production: true }),
      ],
      services: [
        {
          repo: "demo-api",
          name: "api",
          kind: "api",
          description: null,
          endpoints: [
            {
              environment: "staging",
              endpoint: { url: "https://api.staging.example.com" },
              source: "hub.json",
            },
          ],
        },
      ],
      blocked_words: [],
      blocked_files: [],
      blocked_env: [],
    },
  };
}

function open(name: string, routes: ApiRoutes = {}) {
  return renderWithApi(createElement(DiscussProvider, null, createElement(EnvironmentScreen)), {
    routes: { [CONFIG]: aConfig(), ...routes },
    path: `/projects/demo/environment/${name}`,
    route: "projects/:project/environment/:name",
  });
}

describe("EnvironmentScreen", () => {
  it("reads everything agents see about one environment", async () => {
    open("staging");

    expect(await screen.findByRole("heading", { level: 1, name: /staging/ })).toBeVisible();
    expect(screen.getByText("Agents ask before writing", { selector: "span" })).toBeTruthy();
    expect(screen.getAllByText("demo-staging").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("button", {
        name: "Open demo-api › api: https://api.staging.example.com in staging",
      }),
    ).toBeVisible();
    expect(screen.getByRole("complementary", { name: "What agents see" })).toBeVisible();
  });

  it("changes the access in place and saves it for the team", async () => {
    const { requests } = open("staging", { [WRITE]: aConfig() as RouteReply });

    await userEvent.click(
      await screen.findByRole("button", { name: "Change what agents may do in staging" }),
    );
    expect(screen.getByRole("button", { name: "Change description in staging" })).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: "Read only" }));
    await userEvent.click(screen.getByRole("button", { name: "Save access" }));

    expect(await screen.findByText("Saved the access of staging")).toBeVisible();
    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({
      op: "set_environment",
      scope: "team",
      name: "staging",
      access: "read",
      production: false,
    });
  });

  it("only lets me make a team environment stricter for myself", async () => {
    open("staging");

    await userEvent.click(
      await screen.findByRole("button", { name: "Change what agents may do in staging" }),
    );
    await userEvent.click(screen.getByRole("radio", { name: /Only me/ }));

    expect(screen.getByRole("radio", { name: "Can change data" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Read only" })).toBeEnabled();
    expect(screen.getByRole("checkbox", { name: /This is production/ })).toBeDisabled();
  });

  it("saves where the secrets live, by name only", async () => {
    const { requests } = open("staging", { [WRITE]: aConfig() as RouteReply });

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Change secrets for scripted actions in staging",
      }),
    );
    await userEvent.click(screen.getByRole("radio", { name: /In my shell/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "Variable names" }), "DATABASE_URL");
    await userEvent.click(screen.getByRole("button", { name: "Save secrets" }));

    expect(await screen.findByText("Saved the secrets of staging")).toBeVisible();
    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({
      op: "set_environment",
      scope: "team",
      name: "staging",
      env_file: "",
      credential_env: ["DATABASE_URL"],
      aws_profile: "demo-staging",
    });
  });

  it("shows a refused save under the section and keeps the form open", async () => {
    open("staging", {
      [WRITE]: aProblem({
        status: 422,
        title: "This change was not saved",
        errors: [{ pointer: "$", message: "hub.json changed since the page read it" }],
      }),
    });

    await userEvent.click(
      await screen.findByRole("button", { name: "Change description in staging" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save description" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/changed on disk/);
    expect(screen.getByRole("button", { name: "Save description" })).toBeVisible();
  });

  it("offers the team's access back on an environment I tightened", async () => {
    open("live");

    expect(await screen.findByRole("button", { name: "Use the team's access" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Remove environment" })).toBeNull();
  });

  it("says when the environment does not exist", async () => {
    open("stagin");

    expect(await screen.findByText("No environment called stagin")).toBeVisible();
    expect(screen.getByRole("link", { name: "Back to Environments" })).toHaveAttribute(
      "href",
      "/projects/demo/environments",
    );
  });

  it("has no serious a11y violations", async () => {
    const { container } = open("staging");
    await screen.findByRole("heading", { level: 1, name: /staging/ });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
