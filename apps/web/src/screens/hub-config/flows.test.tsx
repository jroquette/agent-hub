import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement } from "react";
import { describe, expect, it } from "vitest";

import { ApiProblem, apiKey } from "../../lib/api";
import { DiscussProvider, useDiscuss } from "../../shell/discuss";
import { seriousViolations } from "../../testing/axe";
import {
  aHubConfigView,
  aProblem,
  aRepoConfigView,
  renderWithApi,
  stubApi,
  testQueryClient,
  type ApiRoutes,
  type HubConfigView,
} from "../../testing/builders";
import { AddEnvironmentScreen } from "./AddEnvironmentFlow";
import { AddServiceScreen } from "./AddServiceFlow";
import { flowOrigin } from "./environments";
import { HubConfigScreen } from "./index";
import { postRepoEdit, repoRefusalOf } from "./repos";

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

/* ---------- Repositories: add, change and remove (AGH-578, 24-hub-config-repos.md) ---------- */

const REPOS = "POST /api/v1/projects/demo/config/repos";

/** demo-api (the project's main) and demo-web (its own trunk, a role and a fast check). */
function twoRepos(overrides: Partial<HubConfigView> = {}): HubConfigView {
  return aHubConfigView({
    repos: [
      aRepoConfigView(),
      aRepoConfigView({
        index: 1,
        dir: "demo-web",
        github: "acme/demo-web",
        role: "web",
        default_branch: {
          value: "trunk",
          source: "team",
          where: "hub.json → repos[1].default_branch",
        },
        check_fast: "make check-fast",
        check_fast_timeout: 120,
      }),
    ],
    ...overrides,
  });
}

function References() {
  const { references } = useDiscuss();
  return createElement(
    "ul",
    { "aria-label": "references" },
    references.map((r) => createElement("li", { key: r.id }, `${r.label}: ${r.quote}`)),
  );
}

function openConfig(routes: ApiRoutes) {
  return renderWithApi(
    createElement(DiscussProvider, null, createElement(HubConfigScreen), createElement(References)),
    { routes, path: "/projects/demo/config", route: "projects/:project/config" },
  );
}

function refusal(...errors: { pointer: string; message: string }[]) {
  return aProblem({ status: 422, title: "This change was not saved", errors });
}

async function posted(requests: Request[]): Promise<unknown> {
  const post = requests.find((r) => r.method === "POST");
  return post?.clone().json();
}

async function repoSection() {
  return screen.findByRole("region", { name: /Repositories/ });
}

describe("Repositories", () => {
  it("repos: posts the edit and stores the returned config", async () => {
    const fresh = twoRepos();
    const requests = stubApi({ [REPOS]: fresh });
    const client = testQueryClient();

    const answer = await postRepoEdit(client, "demo", { op: "remove_repo", dir: "demo-web" });

    expect(answer).toEqual(fresh);
    const key = apiKey("/api/v1/projects/{project}/config", { path: { project: "demo" } });
    expect(client.getQueryData(key)).toEqual(fresh);
    expect(new URL(requests[0]?.url ?? "http://x").pathname).toBe(
      "/api/v1/projects/demo/config/repos",
    );
    expect(await requests[0]?.json()).toEqual({ op: "remove_repo", dir: "demo-web" });
  });

  it("repos: keeps the refusal lines", () => {
    const shown = repoRefusalOf(
      new ApiProblem({
        status: 422,
        title: "This change was not saved",
        errors: [
          {
            pointer: "repos[1].check_fast_timeout",
            message: "hub.json: Input should be less than or equal to 160",
          },
          {
            pointer: "repos[1].github",
            message: "hub.json: String should match pattern '^[A-Za-z0-9_]+$'",
          },
          { pointer: "guard.ask_before_edit[0]", message: "repo demo-web is still named at x" },
          {
            pointer: "repos[0].dir",
            message: "repo demo-web is still named in hub.local.json at repos[0].dir",
          },
        ],
      }),
    );

    expect(shown.title).toBe("This change was not saved");
    expect(shown.changed).toBe(false);
    expect(shown.lines).toEqual([
      {
        field: "check_fast_timeout",
        message: "hub.json: Input should be less than or equal to 160",
      },
      { field: "github", message: "hub.json: owner/name, e.g. acme/demo-web." },
      { field: null, message: "repo demo-web is still named at x" },
      { field: null, message: "repo demo-web is still named in hub.local.json at repos[0].dir" },
    ]);
    expect(repoRefusalOf(new TypeError("offline")).lines).toEqual([
      { field: null, message: "Could not reach the server. Nothing was saved." },
    ]);
    expect(
      repoRefusalOf(
        new ApiProblem({
          status: 422,
          title: "This change was not saved",
          errors: [{ pointer: "$", message: "hub.json changed since this page read it" }],
        }),
      ).changed,
    ).toBe(true);
  });

  it("repos: adds a repo and names ./hub sync", async () => {
    const added = twoRepos();
    const { requests, router } = openConfig({ [CONFIG]: aHubConfigView(), [REPOS]: added });
    const section = await repoSection();

    await userEvent.click(within(section).getByRole("button", { name: "Add repo" }));
    const form = within(section).getByRole("form", { name: "New repo" });
    const folder = within(form).getByRole("textbox", { name: "Folder" });
    expect(folder).toHaveFocus();
    const save = within(form).getByRole("button", { name: "Add repo" });
    expect(save).toBeDisabled();
    expect(within(form).getByText("Fill in the folder, GitHub repo and full check.")).toBeVisible();
    expect(folder).toHaveAttribute("aria-required", "true");
    expect(
      within(form).getByRole("textbox", { name: "Role (optional)" }),
    ).toHaveAccessibleDescription("A word for what the repo is, e.g. api or web. Empty: app.");

    await userEvent.type(folder, "DEMO-API");
    expect(
      within(form).getByText("Already a repo here: demo-api (folders are compared ignoring case)."),
    ).toBeVisible();
    await userEvent.clear(folder);
    await userEvent.type(folder, "demo-web");
    await userEvent.type(
      within(form).getByRole("textbox", { name: "GitHub repo" }),
      "acme/demo-web",
    );
    await userEvent.type(within(form).getByRole("textbox", { name: "Full check" }), "make check");
    await userEvent.type(within(form).getByRole("textbox", { name: "Role (optional)" }), "web");
    await userEvent.click(save);

    expect(await screen.findByText("Added repo demo-web")).toBeVisible();
    expect(await posted(requests)).toEqual({
      op: "add_repo",
      dir: "demo-web",
      github: "acme/demo-web",
      check: "make check",
      role: "web",
    });
    expect(within(section).queryByRole("form", { name: "New repo" })).toBeNull();
    const notice = screen
      .getByText(/hub\.json has changes that are not committed/)
      .closest(".ah-banner");
    expect(notice).toHaveTextContent(
      "Run ./hub sync to update AGENTS.md and .claude/settings.json, then review the diff and open a hub PR.",
    );
    expect(notice).toHaveTextContent("Run ./hub setup to clone ../demo-web.");
    expect(notice).toHaveTextContent("Run /onboard to set demo-web's gates and project rules.");
    expect(router.state.location.search).toBe("?repo=demo-web");
    await waitFor(() => {
      expect(within(section).getByText("demo-web").closest("summary")).toHaveFocus();
    });
  });

  it("repos: shows a 422 message verbatim", async () => {
    openConfig({
      [CONFIG]: aHubConfigView(),
      [REPOS]: refusal({
        pointer: "repos[1].check_fast_timeout",
        message: "hub.json: Input should be less than or equal to 160",
      }),
    });
    const section = await repoSection();

    await userEvent.click(within(section).getByRole("button", { name: "Add repo" }));
    const form = within(section).getByRole("form", { name: "New repo" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Folder" }), "demo-web");
    await userEvent.type(
      within(form).getByRole("textbox", { name: "GitHub repo" }),
      "acme/demo-web",
    );
    await userEvent.type(within(form).getByRole("textbox", { name: "Full check" }), "make check");
    const timeout = within(form).getByRole("textbox", { name: "Fast check timeout (optional)" });
    await userEvent.type(timeout, "x");
    expect(within(form).getByText("Fast check timeout: a whole number of seconds.")).toBeVisible();
    await userEvent.clear(timeout);
    await userEvent.type(timeout, "200{Enter}");

    const alert = await within(form).findByRole("alert");
    expect(alert).toHaveTextContent("This change was not saved");
    expect(within(alert).getByRole("listitem")).toHaveTextContent(
      "hub.json: Input should be less than or equal to 160",
    );
    expect(timeout).toHaveAttribute("aria-invalid", "true");
    expect(timeout).toHaveValue("200");
    expect(within(form).getByRole("textbox", { name: "Folder" })).toHaveValue("demo-web");
  });

  it("repos: changes a repo in place", async () => {
    const changed = twoRepos();
    const { requests } = openConfig({ [CONFIG]: twoRepos(), [REPOS]: changed });
    const section = await repoSection();

    await userEvent.click(within(section).getByRole("button", { name: "Change repo demo-api" }));
    const form = within(section).getByRole("form", { name: "demo-api" });
    expect(within(form).getByRole("textbox", { name: "GitHub repo" })).toHaveFocus();
    expect(within(form).queryByRole("textbox", { name: "Folder" })).toBeNull();
    expect(within(form).getByRole("textbox", { name: "Default branch (optional)" })).toHaveValue(
      "",
    );
    expect(within(form).getByText("Nothing changed yet.")).toBeVisible();
    // One form at a time: the other actions wait for it.
    expect(within(section).getByRole("button", { name: "Add repo" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ask Claude to change the config" })).not.toHaveClass(
      "ah-btn-primary",
    );

    const check = within(form).getByRole("textbox", { name: "Full check" });
    await userEvent.clear(check);
    expect(within(form).getByText("GitHub repo and full check cannot be empty.")).toBeVisible();
    await userEvent.type(check, "make ci");
    await userEvent.click(within(form).getByRole("button", { name: "Save repo" }));

    expect(await screen.findByText("Updated repo demo-api")).toBeVisible();
    expect(await posted(requests)).toEqual({
      op: "set_repo",
      dir: "demo-api",
      check: "make ci",
      unset: [],
    });
    expect(within(section).queryByRole("form")).toBeNull();
    expect(within(section).getByRole("button", { name: "Change repo demo-api" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Ask Claude to change the config" })).toHaveClass(
      "ah-btn-primary",
    );
  });

  it("repos: unsets an optional key", async () => {
    const { requests } = openConfig({ [CONFIG]: twoRepos(), [REPOS]: twoRepos() });
    const section = await repoSection();

    await userEvent.click(within(section).getByRole("button", { name: "Change repo demo-web" }));
    const form = within(section).getByRole("form", { name: "demo-web" });
    expect(within(form).getByRole("textbox", { name: "Default branch (optional)" })).toHaveValue(
      "trunk",
    );
    await userEvent.clear(within(form).getByRole("textbox", { name: "Fast check (optional)" }));
    await userEvent.clear(within(form).getByRole("textbox", { name: "Role (optional)" }));
    await userEvent.clear(within(form).getByRole("textbox", { name: "Default branch (optional)" }));
    await userEvent.click(within(form).getByRole("button", { name: "Save repo" }));

    await screen.findByText("Updated repo demo-web");
    expect(await posted(requests)).toEqual({
      op: "set_repo",
      dir: "demo-web",
      unset: ["check_fast", "role", "default_branch"],
    });
  });

  it("repos: an untouched form whose hub.json value has spaces around it has nothing to save", async () => {
    openConfig({
      [CONFIG]: aHubConfigView({ repos: [aRepoConfigView({ check: "make check " })] }),
    });
    const section = await repoSection();

    await userEvent.click(within(section).getByRole("button", { name: "Change repo demo-api" }));
    const form = within(section).getByRole("form", { name: "demo-api" });

    expect(within(form).getByText("Nothing changed yet.")).toBeVisible();
    expect(within(form).getByRole("button", { name: "Save repo" })).toBeDisabled();
  });

  it("repos: clearing the app role sends nothing", async () => {
    const { requests } = openConfig({ [CONFIG]: twoRepos(), [REPOS]: twoRepos() });
    const section = await repoSection();

    await userEvent.click(within(section).getByRole("button", { name: "Change repo demo-api" }));
    const form = within(section).getByRole("form", { name: "demo-api" });
    await userEvent.clear(within(form).getByRole("textbox", { name: "Role (optional)" }));

    expect(within(form).getByText("Nothing changed yet.")).toBeVisible();
    await userEvent.click(within(form).getByRole("button", { name: "Save repo" }));
    expect(requests.filter((r) => r.method === "POST")).toEqual([]);
  });

  it("repos: sends the fast check timeout as a number", async () => {
    const { requests } = openConfig({ [CONFIG]: twoRepos(), [REPOS]: twoRepos() });
    const section = await repoSection();

    await userEvent.click(within(section).getByRole("button", { name: "Change repo demo-api" }));
    const form = within(section).getByRole("form", { name: "demo-api" });
    await userEvent.type(
      within(form).getByRole("textbox", { name: "Fast check timeout (optional)" }),
      "90",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Save repo" }));

    await screen.findByText("Updated repo demo-api");
    expect(await posted(requests)).toEqual({
      op: "set_repo",
      dir: "demo-api",
      check_fast_timeout: 90,
      unset: [],
    });
  });

  it("repos: clearing the fast check timeout unsets it", async () => {
    const { requests } = openConfig({ [CONFIG]: twoRepos(), [REPOS]: twoRepos() });
    const section = await repoSection();

    await userEvent.click(within(section).getByRole("button", { name: "Change repo demo-web" }));
    const form = within(section).getByRole("form", { name: "demo-web" });
    const timeout = within(form).getByRole("textbox", { name: "Fast check timeout (optional)" });
    expect(timeout).toHaveValue("120");
    await userEvent.clear(timeout);
    await userEvent.click(within(form).getByRole("button", { name: "Save repo" }));

    await screen.findByText("Updated repo demo-web");
    expect(await posted(requests)).toEqual({
      op: "set_repo",
      dir: "demo-web",
      unset: ["check_fast_timeout"],
    });
  });

  it("repos: closes the form when the repo left hub.json on disk", async () => {
    let reads = 0;
    openConfig({
      [CONFIG]: () => {
        reads += 1;
        return reads === 1 ? twoRepos() : aHubConfigView();
      },
      [REPOS]: refusal({ pointer: "$", message: "hub.json changed since this page read it" }),
    });
    const section = await repoSection();

    await userEvent.click(within(section).getByRole("button", { name: "Change repo demo-web" }));
    const form = within(section).getByRole("form", { name: "demo-web" });
    const check = within(form).getByRole("textbox", { name: "Full check" });
    await userEvent.clear(check);
    await userEvent.type(check, "make ci{Enter}");

    expect(
      await within(section).findByText("demo-web is no longer in hub.json. Nothing was saved."),
    ).toBeVisible();
    expect(within(section).queryByRole("form")).toBeNull();
    await waitFor(() => {
      expect(within(section).getByRole("button", { name: "Add repo" })).toHaveFocus();
    });
  });

  it("repos: gives the header Ask its primary look back when the config cannot reload", async () => {
    let reads = 0;
    openConfig({
      [CONFIG]: () => {
        reads += 1;
        return reads === 1 ? twoRepos() : aProblem({ status: 500, title: "Broken" });
      },
      [REPOS]: refusal({ pointer: "$", message: "hub.json changed since this page read it" }),
    });
    const section = await repoSection();

    await userEvent.click(within(section).getByRole("button", { name: "Change repo demo-api" }));
    const ask = screen.getByRole("button", { name: "Ask Claude to change the config" });
    expect(ask).not.toHaveClass("ah-btn-primary");
    const form = within(section).getByRole("form", { name: "demo-api" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Full check" }), "x{Enter}");

    expect(await screen.findByText("Could not read this project's hub.json")).toBeVisible();
    expect(screen.getByRole("button", { name: "Ask Claude to change the config" })).toHaveClass(
      "ah-btn-primary",
    );
  });

  it("repos: an add or a remove refreshes the projects list, a change does not", async () => {
    stubApi({ [REPOS]: twoRepos() });
    const client = testQueryClient();
    const projects = apiKey("/api/v1/projects", { query: { project: null } });
    const stale = () => client.getQueryState(projects)?.isInvalidated;

    client.setQueryData(projects, []);
    await postRepoEdit(client, "demo", { op: "set_repo", dir: "demo-api", unset: ["role"] });
    expect(stale()).toBe(false);

    await postRepoEdit(client, "demo", { op: "remove_repo", dir: "demo-web" });
    expect(stale()).toBe(true);

    client.setQueryData(projects, []);
    await postRepoEdit(client, "demo", {
      op: "add_repo",
      dir: "demo-web",
      github: "acme/demo-web",
      check: "make check",
    });
    expect(stale()).toBe(true);
  });

  it("repos: keeps only the touched fields when hub.json changed on disk", async () => {
    let reads = 0;
    const later = twoRepos();
    later.repos[0] = aRepoConfigView({ github: "acme/api-renamed" });
    openConfig({
      [CONFIG]: () => {
        reads += 1;
        return reads === 1 ? twoRepos() : later;
      },
      [REPOS]: refusal({ pointer: "$", message: "hub.json changed since this page read it" }),
    });
    const section = await repoSection();

    await userEvent.click(within(section).getByRole("button", { name: "Change repo demo-api" }));
    const form = within(section).getByRole("form", { name: "demo-api" });
    const check = within(form).getByRole("textbox", { name: "Full check" });
    await userEvent.clear(check);
    await userEvent.type(check, "make ci{Enter}");

    expect(
      await within(form).findByText(
        "hub.json changed on disk since this page loaded. Nothing was saved. The page now shows the file as it is; check and save again.",
      ),
    ).toBeVisible();
    await waitFor(() => {
      expect(within(form).getByRole("textbox", { name: "GitHub repo" })).toHaveValue(
        "acme/api-renamed",
      );
    });
    expect(check).toHaveValue("make ci");
  });

  it("repos: removes a repo", async () => {
    const left = aHubConfigView();
    const { requests, router } = openConfig({
      [CONFIG]: twoRepos({
        environments: {
          ...aHubConfigView().environments,
          services: [
            { repo: "demo-web", name: "web", kind: "web", description: null, endpoints: [] },
          ],
        },
      }),
      [REPOS]: left,
    });
    const section = await repoSection();

    await userEvent.click(within(section).getByText("demo-web"));
    await userEvent.click(within(section).getByRole("button", { name: "Remove repo demo-web" }));
    const dialog = screen.getByRole("alertdialog", { name: "Remove repo demo-web?" });
    expect(dialog).toHaveTextContent("Agents stop working in demo-web after ./hub sync.");
    expect(dialog).toHaveTextContent("Its 1 services go with it: web.");
    expect(dialog).toHaveTextContent("../demo-web and its worktrees stay on disk.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove repo" }));

    expect(await screen.findByText("Removed repo demo-web")).toBeVisible();
    expect(await posted(requests)).toEqual({ op: "remove_repo", dir: "demo-web" });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    const notice = screen
      .getByText(/hub\.json has changes that are not committed/)
      .closest(".ah-banner");
    expect(notice).toHaveTextContent("../demo-web and its worktrees are left in place.");
    expect(notice).toHaveTextContent(
      "A teammate whose hub.local.json names demo-web in repos must drop that entry.",
    );
    // ?repo= named the removed repo: it is dropped, and the first card opens by default. The
    // first card's toggle event comes in a later task: let it run before reading the URL.
    const first = within(section).getByText("demo-api").closest("details");
    await waitFor(() => {
      expect(first).toHaveAttribute("open");
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(new URLSearchParams(router.state.location.search).get("repo")).toBeNull();
    expect(within(section).getByRole("button", { name: "Add repo" })).toHaveFocus();
  });

  it("repos: lists each reference when remove is refused", async () => {
    openConfig({
      [CONFIG]: twoRepos(),
      [REPOS]: refusal(
        {
          pointer: "guard.ask_before_edit[0]",
          message: "repo demo-web is still named at guard.ask_before_edit[0]",
        },
        {
          pointer: "repos[0].dir",
          message: "repo demo-web is still named in hub.local.json at repos[0].dir",
        },
      ),
    });
    const section = await repoSection();

    await userEvent.click(within(section).getByText("demo-web"));
    await userEvent.click(within(section).getByRole("button", { name: "Remove repo demo-web" }));
    const dialog = screen.getByRole("alertdialog", { name: "Remove repo demo-web?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove repo" }));

    const alert = await within(dialog).findByRole("alert");
    expect(
      within(alert)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "repo demo-web is still named at guard.ask_before_edit[0]",
      "repo demo-web is still named in hub.local.json at repos[0].dir",
    ]);
    expect(within(dialog).getByRole("button", { name: "Remove repo" })).toBeEnabled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Ask Claude to drop these" }));

    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("list", { name: "references" })).toHaveTextContent(
      "repo demo-web is still named in hub.local.json at repos[0].dir",
    );
  });

  it("repos: keeps Remove off with its reason when there is one repo", async () => {
    openConfig({ [CONFIG]: aHubConfigView() });
    const section = await repoSection();

    const remove = within(section).getByRole("button", { name: "Remove repo demo-api" });
    expect(remove).toBeDisabled();
    expect(remove).toHaveAccessibleDescription("The only repo: hub.json needs at least one.");
  });
});
