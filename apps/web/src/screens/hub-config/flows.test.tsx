import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { renderWithApi, type ApiRoutes } from "../../testing/builders";
import { AddEnvironmentScreen } from "./AddEnvironmentFlow";
import { AddServiceScreen } from "./AddServiceFlow";
import { flowOrigin } from "./environments";

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
    path: "/projects/demo/environments/new",
    route: "projects/:project/environments/new",
  });
}

function openService(routes: ApiRoutes = { [CONFIG]: aConfig(TWO_ENVIRONMENTS) }) {
  return renderWithApi(<AddServiceScreen />, {
    routes,
    path: "/projects/demo/environments/services/new",
    route: "projects/:project/environments/services/new",
  });
}

const next = () => userEvent.click(screen.getByRole("button", { name: /^(Continue|Skip)$/ }));

describe("AddEnvironmentScreen", () => {
  it("AC-417.13 asks one question per step and fills production from its kind", async () => {
    const { requests, router } = openEnvironment({ [CONFIG]: aConfig(), [WRITE]: aConfig() });

    expect(
      await screen.findByRole("heading", { name: /What kind of environment is it\?$/ }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: /Production/ }));
    await next();

    expect(screen.getByRole("heading", { name: /What do you call it\?$/ })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("production");
    await next();

    expect(screen.getByRole("radio", { name: "Read only" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /This is production/ })).toBeChecked();
    await next();
    expect(screen.getByRole("radio", { name: /The whole team/ })).toBeChecked();
    await next();
    await next();

    expect(screen.getByRole("heading", { name: /Add production\?$/ })).toBeVisible();
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
    expect(router.state.location.pathname).toBe("/projects/demo/environments");
    expect(router.state.location.state).toEqual({
      saved: "Added production for the team",
      team: true,
    });
  });

  it("AC-417.14 keeps a variable line holding a value from going on", async () => {
    openEnvironment();

    await userEvent.click(await screen.findByRole("radio", { name: /My own copy/ }));
    await next();
    await next();
    await next();
    await next();
    await userEvent.click(screen.getByRole("radio", { name: /In my shell/ }));
    await userEvent.type(
      screen.getByRole("textbox", { name: "Variable names" }),
      "DB_URL=postgres://x",
    );

    expect(screen.getByText("Line 1: only the name. Remove = and what follows.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it("AC-417.14 lists the env file's variable names and sends only the file", async () => {
    const { requests } = openEnvironment({
      [CONFIG]: aConfig(),
      [WRITE]: aConfig(),
      "/api/v1/projects/demo/env-file-keys": {
        path: "demo-api/dotenv.staging",
        exists: true,
        holder: "demo-api",
        ignored: false,
        keys: ["DATABASE_URL", "STRIPE_KEY"],
        truncated: false,
        problem: null,
      },
    });

    await userEvent.click(await screen.findByRole("radio", { name: /Test or staging/ }));
    await next();
    await next();
    await next();
    await next();
    expect(screen.getByRole("button", { name: "Skip" })).toBeEnabled();
    await userEvent.click(screen.getByRole("radio", { name: /In an env file/ }));
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.type(
      screen.getByRole("textbox", { name: "Env file path" }),
      "demo-api/dotenv.staging",
    );

    const listed = await screen.findByRole("list", { name: "Variables in the env file" });
    expect(listed).toHaveTextContent("DATABASE_URL");
    expect(listed).toHaveTextContent("STRIPE_KEY");
    expect(screen.getByText(/git does not ignore this file in demo-api/)).toBeVisible();
    await next();
    await userEvent.click(screen.getByRole("button", { name: /Add environment for/ }));

    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toMatchObject({
      env_file: "demo-api/dotenv.staging",
      credential_env: [],
    });
    const asked = requests.find((r) => r.url.includes("env-file-keys"));
    expect(new URL(asked?.url ?? "http://x").searchParams.get("path")).toBe(
      "demo-api/dotenv.staging",
    );
  });

  it("AC-417.15 refuses a name another environment has, ignoring case", async () => {
    openEnvironment({ [CONFIG]: aConfig(TWO_ENVIRONMENTS) });

    await userEvent.click(await screen.findByRole("radio", { name: /This machine/ }));
    await next();
    const name = screen.getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "LOCAL");

    expect(screen.getByText("local already exists. Pick another name.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it("AC-417.13 goes back to a done step from the step list", async () => {
    openEnvironment();

    await userEvent.click(await screen.findByRole("radio", { name: /Test or staging/ }));
    await next();
    const steps = screen.getByRole("list", { name: "Steps" });
    await userEvent.click(within(steps).getByRole("button", { name: "Back to step 1: Kind" }));

    expect(
      screen.getByRole("heading", { name: /What kind of environment is it\?$/ }),
    ).toBeVisible();
    expect(screen.getByRole("radio", { name: /Test or staging/ })).toBeChecked();
  });

  it("AC-417.17 asks before discarding answers past the first step, and leaves at once on it", async () => {
    const { router } = openEnvironment();

    await userEvent.click(await screen.findByRole("radio", { name: /Test or staging/ }));
    await next();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    const ask = screen.getByRole("alertdialog", { name: "Discard this environment?" });
    await userEvent.click(within(ask).getByRole("button", { name: "Keep editing" }));
    expect(screen.getByRole("heading", { name: /What do you call it\?$/ })).toBeVisible();

    await userEvent.click(
      within(screen.getByRole("list", { name: "Steps" })).getByRole("button", {
        name: "Back to step 1: Kind",
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(router.state.location.pathname).toBe("/projects/demo/environments");
  });

  it("has no serious a11y violations", async () => {
    const { container } = openEnvironment();
    await screen.findByRole("heading", { name: /What kind of environment is it\?$/ });

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("AddServiceScreen", () => {
  it("AC-417.16 adds a portal with an address per environment", async () => {
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
    await userEvent.type(
      screen.getByRole("textbox", { name: "Address in local" }),
      "http://localhost:3000",
    );
    await userEvent.type(
      screen.getByRole("textbox", { name: "Address in live" }),
      "https://app.example.com",
    );
    await next();

    expect(screen.getByRole("heading", { name: /Add demo-web › web\?$/ })).toBeVisible();
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

  it("AC-417.16 sends people to add an environment first when there is none", async () => {
    openService({ [CONFIG]: aConfig() });

    expect(await screen.findByText("Add an environment first")).toBeVisible();
    expect(screen.getByRole("link", { name: "Add environment" })).toHaveAttribute(
      "href",
      "/projects/demo/environments/new",
    );
  });

  it("has no serious a11y violations", async () => {
    const { container } = openService();
    await screen.findByRole("heading", { name: /What runs\?$/ });

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("flowOrigin", () => {
  it("AC-417.17 returns to the page that opened the flow, only within the project", () => {
    const page = { returnTo: "/projects/demo/environments", returnLabel: "Environments" };
    const config = {
      returnTo: "/projects/demo/environments",
      returnLabel: "Environments",
    };

    expect(flowOrigin(page, "demo")).toEqual(page);
    expect(flowOrigin({ returnTo: "https://evil.example", returnLabel: "x" }, "demo")).toEqual(
      config,
    );
    expect(flowOrigin(null, "demo")).toEqual(config);
  });
});
