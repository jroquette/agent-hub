import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { renderWithApi, type ApiRoutes } from "../../testing/builders";
import { AddEnvironmentScreen } from "./AddEnvironmentFlow";
import { AddServiceScreen } from "./AddServiceFlow";

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

/** The config fields the flows read; the rest of the view is not used by them. */
function aConfig(environments: unknown[] = []) {
  return {
    project: "demo",
    local_file: { name: "hub.local.json", path: "/hubs/demo-hub/hub.local.json", problems: [] },
    repos: [
      { dir: "demo-api", github: "acme/demo-api", role: "backend" },
      { dir: "demo-web", github: "acme/demo-web", role: "frontend" },
    ],
    environments: {
      environments,
      services: [],
      blocked_words: [],
      blocked_files: [],
      blocked_env: [],
    },
  };
}

const TWO_ENVIRONMENTS = [
  environment("local", "write", "hub.json"),
  environment("live", "read", "hub.json", { production: true }),
];

function openEnvironment(routes: ApiRoutes = { [CONFIG]: aConfig() }) {
  return renderWithApi(<AddEnvironmentScreen />, {
    routes,
    path: "/projects/demo/config/environments/new",
    route: "projects/:project/config/environments/new",
  });
}

function openService(routes: ApiRoutes = { [CONFIG]: aConfig(TWO_ENVIRONMENTS) }) {
  return renderWithApi(<AddServiceScreen />, {
    routes,
    path: "/projects/demo/config/services/new",
    route: "projects/:project/config/services/new",
  });
}

const next = () => userEvent.click(screen.getByRole("button", { name: /^(Continue|Skip)$/ }));

describe("AddEnvironmentScreen", () => {
  it("asks one question per step and fills production from its kind", async () => {
    const { requests, router } = openEnvironment({ [CONFIG]: aConfig(), [WRITE]: aConfig() });

    expect(
      await screen.findByRole("heading", { name: "What kind of environment is it?" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: /Production/ }));
    await next();

    expect(screen.getByRole("heading", { name: "What do you call it?" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("production");
    await next();

    expect(screen.getByRole("radio", { name: "Read only" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /This is production/ })).toBeChecked();
    await next();
    expect(screen.getByRole("radio", { name: /The whole team/ })).toBeChecked();
    await next();
    await next();

    expect(screen.getByRole("heading", { name: "Add production?" })).toBeVisible();
    expect(screen.getByText(/Run/)).toHaveTextContent("./hub sync");
    await userEvent.click(screen.getByRole("button", { name: "Add environment for the team" }));

    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toMatchObject({
      op: "add_environment",
      scope: "team",
      name: "production",
      access: "read",
      production: true,
    });
    expect(router.state.location.pathname).toBe("/projects/demo/config");
    expect(router.state.location.state).toEqual({
      saved: "Added production for the team",
      team: true,
    });
  });

  it("keeps a variable line holding a value from going on", async () => {
    openEnvironment();

    await userEvent.click(await screen.findByRole("radio", { name: /My own copy/ }));
    await next();
    await next();
    await next();
    await next();
    await userEvent.type(
      screen.getByRole("textbox", { name: "Variable names" }),
      "DB_URL=postgres://x",
    );

    expect(screen.getByText("Line 1: only the name. Remove = and what follows.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it("refuses a name another environment has, ignoring case", async () => {
    openEnvironment({ [CONFIG]: aConfig(TWO_ENVIRONMENTS) });

    await userEvent.click(await screen.findByRole("radio", { name: /This machine/ }));
    await next();
    const name = screen.getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "LOCAL");

    expect(screen.getByText("local already exists. Pick another name.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it("goes back to a done step from the step list", async () => {
    openEnvironment();

    await userEvent.click(await screen.findByRole("radio", { name: /Test or staging/ }));
    await next();
    const steps = screen.getByRole("list", { name: "Steps" });
    await userEvent.click(within(steps).getByRole("button", { name: "Back to step 1: Kind" }));

    expect(screen.getByRole("heading", { name: "What kind of environment is it?" })).toBeVisible();
    expect(screen.getByRole("radio", { name: /Test or staging/ })).toBeChecked();
  });

  it("has no serious a11y violations", async () => {
    const { container } = openEnvironment();
    await screen.findByRole("heading", { name: "What kind of environment is it?" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("AddServiceScreen", () => {
  it("adds a portal with an address per environment", async () => {
    const { requests, router } = openService({
      [CONFIG]: aConfig(TWO_ENVIRONMENTS),
      [WRITE]: aConfig(TWO_ENVIRONMENTS),
    });

    await userEvent.click(await screen.findByRole("radio", { name: /Frontend or portal/ }));
    await next();
    await userEvent.click(screen.getByRole("radio", { name: /demo-web/ }));
    expect(screen.getByRole("textbox", { name: "Service name" })).toHaveValue("web");
    await next();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox", { name: "local" }), "http://localhost:3000");
    await userEvent.type(screen.getByRole("textbox", { name: /live/ }), "https://app.example.com");
    await next();

    expect(screen.getByRole("heading", { name: "Add demo-web › web?" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Add service" }));

    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({
      op: "add_service",
      repo: "demo-web",
      service: "web",
      kind: "web",
      addresses: [
        { environment: "local", address: "http://localhost:3000" },
        { environment: "live", address: "https://app.example.com" },
      ],
    });
    expect(router.state.location.state).toEqual({ saved: "Added demo-web › web", team: true });
  });

  it("sends people to add an environment first when there is none", async () => {
    openService({ [CONFIG]: aConfig() });

    expect(await screen.findByText("Add an environment first")).toBeVisible();
    expect(screen.getByRole("link", { name: "Add environment" })).toHaveAttribute(
      "href",
      "/projects/demo/config/environments/new",
    );
  });

  it("has no serious a11y violations", async () => {
    const { container } = openService();
    await screen.findByRole("heading", { name: "What runs?" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
