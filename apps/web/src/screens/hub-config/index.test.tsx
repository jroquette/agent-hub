import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { DiscussProvider, useDiscuss } from "../../shell/discuss";
import { seriousViolations } from "../../testing/axe";
import {
  aPage,
  aProblem,
  aProjectSummary,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { HubConfigPickerScreen, HubConfigScreen } from "./index";

const CONFIG = "/api/v1/projects/demo/config";

function sourced(
  value: string | null,
  source: string,
  where: string,
  team_value: string | null = null,
) {
  return { value, source, where, team_value };
}

function pattern(value: string, source: string, where: string, example: string | null) {
  return { pattern: value, source, where, example };
}

function aConfig(overrides: Record<string, unknown> = {}) {
  const commit = pattern(
    "{type}({scope}): {summary} ({ISSUE})",
    "repo",
    "hub.json → repos[0].conventions.commit_title",
    "feat(api): add the hub config view (DEM-42)",
  );
  return {
    project: "demo",
    hub_path: "/hubs/demo-hub",
    hub_repo: "acme/demo-hub",
    team_file: { name: "hub.json", path: "/hubs/demo-hub/hub.json", problems: [] },
    local_file: { name: "hub.local.json", path: "/hubs/demo-hub/hub.local.json", problems: [] },
    author_name: sourced("Jane Doe", "team", "hub.json → project.author_name", "Jane Doe"),
    author_email: sourced(
      "me@example.com",
      "local",
      "hub.local.json → project.author_email",
      "jane@example.com",
    ),
    branch_prefix: sourced("jdoe/", "team", "hub.json → project.branch_prefix", "jdoe/"),
    default_branch: sourced("main", "default", "built-in default (main)"),
    conventions: [
      pattern(
        "{prefix}{issue_lower}-{slug}",
        "default",
        "built-in default",
        "jdoe/dem-42-hub-config",
      ),
      commit,
      pattern(commit.pattern, "commit_title", "follows the commit title", commit.example),
    ],
    repos: [
      {
        index: 0,
        dir: "demo-api",
        github: "acme/demo-api",
        role: "app",
        default_branch: sourced("develop", "team", "hub.json → repos[0].default_branch"),
        branch: pattern(
          "{prefix}{issue_lower}-{slug}",
          "default",
          "built-in default",
          "jdoe/dem-42-hub-config",
        ),
        commit_title: commit,
        pr_title: pattern(
          commit.pattern,
          "commit_title",
          "follows the commit title",
          commit.example,
        ),
        check_fast: "make check-fast",
        check_fast_timeout: 120,
        check: "make check",
      },
    ],
    tracker: {
      kind: "linear",
      teams: ["DEM"],
      transport: sourced("api", "default", "built-in default (api)"),
      ready_label: "agent-ready",
      failed_label: "agent-failed",
      blocked_label: null,
      started_state: "In Progress",
      review_state: "In Review",
      team_set: [],
    },
    guard: {
      blocked_words: { team: ["acme-prod"], local: ["my-client"] },
      blocked_words_files: { team: [], local: [] },
      blocked_words_env: { team: [], local: [] },
      deny_paths: [],
      ask_before_edit: ["demo-api/docs/adr"],
      deny_hosts: [],
      secret_env_files: [],
      readable_env_files: [],
      infra_on: false,
    },
    model_tiers: { small: "haiku", medium: "sonnet", large: "opus" },
    model_tiers_set: [],
    agent_models: [],
    modules: ["cloud"],
    platform_version: "0.2.0",
    environments: {
      environments: [],
      services: [],
      blocked_words: [],
      blocked_files: [],
      blocked_env: [],
    },
    ...overrides,
  };
}

const ENV_WRITE = "POST /api/v1/projects/demo/config/environments";

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

function withEnvironments() {
  return aConfig({
    environments: {
      environments: [
        environment("local", "write", "hub.json", { description: "docker compose stack" }),
        environment("live", "read", "hub.json", {
          production: true,
          credentials: { aws_profile: "demo-live-ro", env: ["DEMO_LIVE_DB_URL"] },
        }),
        environment("staging", "read", "hub.local.json", { team_access: "write" }),
        environment("jane-cloud", "write", "hub.local.json"),
      ],
      services: [
        {
          repo: "demo-api",
          name: "api",
          kind: "api",
          description: null,
          endpoints: [
            {
              environment: "local",
              endpoint: { url: "http://localhost:8000" },
              source: "hub.json",
            },
            {
              environment: "jane-cloud",
              endpoint: { url: "https://api.jane.example.com" },
              source: "hub.local.json",
            },
          ],
        },
      ],
      blocked_words: [],
      blocked_files: [],
      blocked_env: [],
    },
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

function open(path = "/projects/demo/config", routes: ApiRoutes = { [CONFIG]: aConfig() }) {
  return renderWithApi(
    createElement(DiscussProvider, null, createElement(HubConfigScreen), createElement(References)),
    { routes, path, route: "projects/:project/config" },
  );
}

describe("HubConfigScreen", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("shows each repo's default branch and commit pattern with its source and an example", async () => {
    open();

    const repos = await screen.findByRole("region", { name: /Repositories/ });
    expect(within(repos).getByText("develop")).toBeVisible();
    expect(within(repos).getAllByText("{type}({scope}): {summary} ({ISSUE})")[0]).toBeVisible();
    expect(
      within(repos).getAllByText("feat(api): add the hub config view (DEM-42)")[0],
    ).toBeVisible();
    expect(within(repos).getAllByText("Set by the team")[0]).toBeVisible();
    expect(within(repos).getByText("Same as the commit title")).toBeVisible();
  });

  it("says who commits and who set each value", async () => {
    open();

    const who = await screen.findByRole("region", { name: /Who commits/ });
    expect(within(who).getByText("me@example.com")).toBeVisible();
    expect(within(who).getByText("Set by you")).toBeVisible();
  });

  it("points Claude at the commit title row without leaving the screen", async () => {
    open();

    await userEvent.click(
      await screen.findByRole("button", { name: "Ask Claude to change commit title of demo-api" }),
    );

    const list = screen.getByRole("list", { name: "references" });
    expect(list).toHaveTextContent("Commit title · demo-api");
    expect(list).toHaveTextContent(
      'repos[0].conventions.commit_title: "{type}({scope}): {summary} ({ISSUE})"',
    );
  });

  it("keeps blocked words behind Show words and out of Claude's message", async () => {
    open();

    const guard = await screen.findByRole("region", { name: /Guard/ });
    expect(within(guard).queryByText("acme-prod")).toBeNull();
    expect(within(guard).getByText("2 words: 1 from the team, 1 added by you")).toBeVisible();
    await userEvent.click(
      within(guard).getByRole("button", { name: "Ask Claude to change blocked words" }),
    );
    expect(screen.getByRole("list", { name: "references" })).not.toHaveTextContent("acme-prod");
    await userEvent.click(within(guard).getByRole("button", { name: "Show words" }));
    expect(within(guard).getByText("acme-prod")).toBeVisible();
  });

  it("names the team's value my own value overrides, on the row", async () => {
    open();

    const who = await screen.findByRole("region", { name: /Who commits/ });
    expect(within(who).getByText(/Overrides the team's/)).toHaveTextContent("jane@example.com");
  });

  it("opens my settings from a row I may set", async () => {
    open();

    await userEvent.click(
      await screen.findByRole("button", { name: "Change for me: author email" }),
    );
    expect(screen.getByRole("dialog", { name: "Change my settings" })).toBeVisible();
  });

  it("marks a team-only value built-in when hub.json does not set it", async () => {
    open("/projects/demo/config", {
      [CONFIG]: aConfig({ model_tiers_set: ["large"] }),
    });

    const models = await screen.findByRole("region", { name: /Models/ });
    expect(within(models).getAllByText("Built-in")).toHaveLength(2);
    expect(within(models).getByText("Set by the team")).toBeVisible();
  });

  it("marks the tracker's labels built-in and its states the team's when hub.json sets only a state", async () => {
    open("/projects/demo/config", {
      [CONFIG]: aConfig({ tracker: { ...aConfig().tracker, team_set: ["review_state"] } }),
    });

    const tracker = await screen.findByRole("region", { name: /Tracker/ });
    const row = (label: string) => {
      const cell = within(tracker).getByText(label, { selector: ".ah-config-label" });
      const parent = cell.closest(".ah-config-row");
      if (!(parent instanceof HTMLElement)) throw new Error(`no row ${label}`);
      return within(parent);
    };
    expect(row("Labels").getByText("Built-in")).toBeVisible();
    expect(row("States").getByText("Set by the team")).toBeVisible();
  });

  it("offers Change for me, or Add for me on a list, only on the rows I may set", async () => {
    open();

    const guard = await screen.findByRole("region", { name: /Guard/ });
    expect(within(guard).getByRole("button", { name: "Add for me: blocked words" })).toBeVisible();
    expect(within(guard).queryByRole("button", { name: /for me: never read/ })).toBeNull();
    const tracker = screen.getByRole("region", { name: /Tracker/ });
    expect(within(tracker).getByRole("button", { name: "Change for me: transport" })).toBeVisible();
    expect(within(tracker).queryByRole("button", { name: /Change for me: labels/ })).toBeNull();
    const models = screen.getByRole("region", { name: /Models/ });
    expect(within(models).queryByRole("button", { name: /Change for me/ })).toBeNull();
  });

  it("saves the local settings to hub.local.json and shows the field's problem in words", async () => {
    const { requests } = open("/projects/demo/config", {
      [CONFIG]: aConfig(),
      "PUT /api/v1/projects/demo/config/local": aProblem({
        status: 422,
        title: "These local settings are not valid",
        errors: [
          { pointer: "project.branch_prefix", message: "String should match pattern '^x$'" },
        ],
      }),
    });

    await userEvent.click(await screen.findByRole("button", { name: "Change my settings" }));
    const dialog = screen.getByRole("dialog", { name: "Change my settings" });
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Branch prefix" }), "nope");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save my settings" }));

    expect(await within(dialog).findByText(/Must end with \//)).toBeVisible();
    const put = requests.find((r) => r.method === "PUT");
    expect(await put?.json()).toMatchObject({
      branch_prefix: "nope",
      author_email: "me@example.com",
    });
  });

  it("disables the Ask buttons with the reason when session control is locked", async () => {
    open("/projects/demo/config", {
      [CONFIG]: aConfig(),
      "/api/v1/agent-sessions/capabilities": aProblem({ status: 401, title: "Unauthorized" }),
    });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Ask Claude to change the config" }),
      ).toBeDisabled();
    });
    expect(
      screen.getByRole("button", {
        name: (name) =>
          name.startsWith("Ask Claude to change commit title of demo-api (unavailable"),
      }),
    ).toBeDisabled();
  });

  it("marks the list a refused blocked word is in, with its line", async () => {
    open("/projects/demo/config", {
      [CONFIG]: aConfig(),
      "PUT /api/v1/projects/demo/config/local": aProblem({
        status: 422,
        title: "These local settings are not valid",
        errors: [{ pointer: "guard.blocked_words[1]", message: "must not hold a space" }],
      }),
    });

    await userEvent.click(await screen.findByRole("button", { name: "Change my settings" }));
    const dialog = screen.getByRole("dialog", { name: "Change my settings" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Save my settings" }));

    const words = within(dialog).getByRole("textbox", { name: "Blocked words" });
    await waitFor(() => {
      expect(words).toHaveAttribute("aria-invalid", "true");
    });
    expect(within(dialog).getByText("Line 2: Must not hold a space")).toBeVisible();
  });

  it("confirms a save of the local settings", async () => {
    open("/projects/demo/config", {
      [CONFIG]: aConfig(),
      "PUT /api/v1/projects/demo/config/local": aConfig(),
    });

    await userEvent.click(await screen.findByRole("button", { name: "Change my settings" }));
    await userEvent.click(screen.getByRole("button", { name: "Save my settings" }));

    expect(await screen.findByText("Saved your settings")).toBeVisible();
  });

  it("explains a hub.json it cannot read", async () => {
    open("/projects/demo/config", {
      [CONFIG]: aProblem({ status: 404, title: "Project not found", detail: "No project demo." }),
    });

    expect(await screen.findByText("Project not found")).toBeVisible();
  });

  it("AC-PG-38.2 opens a project picker at /config with All projects in scope", async () => {
    renderWithApi(createElement(HubConfigPickerScreen), {
      routes: { "/api/v1/projects": aPage([aProjectSummary({ name: "demo" })]) },
      path: "/config",
    });

    expect(
      await screen.findByRole("heading", { level: 1, name: "Hub configuration" }),
    ).toBeVisible();
    expect(await screen.findByRole("link", { name: "demo" })).toHaveAttribute(
      "href",
      "/projects/demo/config",
    );
  });

  it("AC-PG-38.2 opens the project in scope's configuration from /config", async () => {
    const { router } = renderWithApi(createElement(HubConfigPickerScreen), {
      routes: { "/api/v1/projects": aPage([aProjectSummary({ name: "demo" })]) },
      path: "/config?scope=demo",
    });

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/projects/demo/config");
    });
  });

  it("AC-PG-38.2 shows one view of the values agents use, whatever an old layer link says", async () => {
    open("/projects/demo/config?layer=local");

    const rail = await screen.findByRole("navigation", { name: "On this page" });
    expect(within(rail).getByRole("link", { name: "Models" })).toBeVisible();
    expect(screen.queryByRole("radiogroup", { name: "Layer" })).toBeNull();
  });

  it("AC-PG-38.2 lists Models in the Effective view", async () => {
    open();

    const rail = await screen.findByRole("navigation", { name: "On this page" });
    expect(within(rail).getByRole("link", { name: "Models" })).toBeVisible();
    expect(screen.getByRole("region", { name: /Models/ })).toBeVisible();
  });

  it("AC-PG-38.2 hides the team and local guard words until Show words", async () => {
    open();

    const guard = await screen.findByRole("region", { name: /Guard/ });
    expect(within(guard).queryByText("acme-prod")).toBeNull();
    expect(within(guard).queryByText("my-client")).toBeNull();
    await userEvent.click(within(guard).getByRole("button", { name: "Show words" }));
    expect(within(guard).getByText("acme-prod")).toBeVisible();
    expect(within(guard).getByText("my-client")).toBeVisible();
  });

  it("AC-PG-38.3 says in words that a row pointed at goes in the next message", async () => {
    open();

    await userEvent.click(
      await screen.findByRole("button", { name: "Ask Claude to change commit title of demo-api" }),
    );

    expect(
      screen.getByRole("button", {
        name: "Ask Claude to change commit title of demo-api: in next message",
      }),
    ).toBeVisible();
    expect(screen.getAllByText("In next message").length).toBeGreaterThan(0);
  });

  it("AC-PG-38.3 names the reason a row's Ask is disabled when session control is locked", async () => {
    open("/projects/demo/config", {
      [CONFIG]: aConfig(),
      "/api/v1/agent-sessions/capabilities": aProblem({ status: 401, title: "Unauthorized" }),
    });

    const row = await screen.findByRole("button", {
      name: (name) => name.startsWith("Ask Claude to change commit title of demo-api (unavailable"),
    });
    expect(row).toBeDisabled();
    expect(row).toHaveAccessibleName(
      expect.stringContaining("Session control is locked in this browser") as string,
    );
  });

  it("AC-PG-38.6 says once where values come from, and keeps it hidden once hidden", async () => {
    open();

    const explainer = await screen.findByRole("region", { name: "Where values come from" });
    expect(within(explainer).getByText(/You set 2 values on this machine/)).toBeVisible();
    await userEvent.click(within(explainer).getByRole("button", { name: "Hide" }));

    expect(screen.queryByRole("region", { name: "Where values come from" })).toBeNull();
    expect(window.localStorage.getItem("ah.config.explainer")).toBe("hidden");
    await userEvent.click(screen.getByRole("button", { name: "Show where values come from" }));
    expect(screen.getByRole("region", { name: "Where values come from" })).toBeVisible();
  });

  it("AC-PG-38.6 offers Ask Claude to fix an unreadable hub.local.json", async () => {
    open("/projects/demo/config", {
      [CONFIG]: aConfig({
        local_file: {
          name: "hub.local.json",
          path: "/hubs/demo-hub/hub.local.json",
          problems: ["line 3: expected ','"],
        },
      }),
    });

    expect(
      await screen.findByText(/has a problem, so only the team's values apply/),
    ).toHaveTextContent("line 3: expected ','");
    await userEvent.click(screen.getByRole("button", { name: "Ask Claude to fix it" }));
    expect(screen.getByRole("list", { name: "references" })).toHaveTextContent(
      "hub.local.json problems: line 3: expected ','",
    );
  });

  it("has no serious a11y violations", async () => {
    const { container } = open();
    await screen.findByRole("region", { name: /Repositories/ });

    // One axe pass once the screen has loaded, as the other screens' checks: inside waitFor its
    // 1 s budget timed a slow pass out on a busy machine.
    expect(await seriousViolations(container)).toEqual([]);
  });
  it("lists each environment with what agents may do there and who set it", async () => {
    open("/projects/demo/config", { [CONFIG]: withEnvironments() });

    const section = await screen.findByRole("region", { name: /Environments/ });
    expect(within(section).getAllByText("Agents may change data")).toHaveLength(2);
    expect(within(section).getAllByText("Agents only read")).toHaveLength(2);
    expect(within(section).getAllByText("Production").length).toBeGreaterThan(0);
    expect(within(section).getByText("Tightened by you")).toBeVisible();
    expect(within(section).getByText("Team: may change data")).toBeVisible();
    expect(within(section).getByText("demo-live-ro")).toBeVisible();
    expect(within(section).getByText("DEMO_LIVE_DB_URL")).toBeVisible();
    expect(
      within(section).getByRole("button", {
        name: "Edit endpoint of demo-api › api in local: http://localhost:8000",
      }),
    ).toBeVisible();
    expect(
      within(section).getByRole("button", { name: "Add endpoint for demo-api › api in live" }),
    ).toBeVisible();
  });

  it("explains environments and offers to add one when none is declared", async () => {
    open();

    const section = await screen.findByRole("region", { name: /Environments/ });
    expect(within(section).getByText("No environments yet")).toBeVisible();
    expect(within(section).getByRole("button", { name: "Add environment" })).toBeVisible();
  });

  it("adds a team environment and says hub.json is not committed", async () => {
    const { requests } = open("/projects/demo/config", {
      [CONFIG]: aConfig(),
      [ENV_WRITE]: withEnvironments(),
    });

    await userEvent.click(await screen.findByRole("button", { name: "Add environment" }));
    const dialog = screen.getByRole("dialog", { name: "Add environment" });
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Name" }), "staging");
    await userEvent.click(within(dialog).getByRole("radio", { name: "The whole team" }));
    await userEvent.click(within(dialog).getByRole("radio", { name: "Ask first" }));
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "AWS profile name" }),
      "demo-staging",
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Add environment for the team" }),
    );

    expect(await screen.findByText("Added staging for the team")).toBeVisible();
    expect(screen.getByText(/hub.json has changes that are not committed/)).toBeVisible();
    const post = requests.find((r) => r.method === "POST" && r.url.endsWith("/environments"));
    expect(await post?.json()).toMatchObject({
      op: "add_environment",
      scope: "team",
      name: "staging",
      access: "ask",
      aws_profile: "demo-staging",
    });
  });

  it("refuses a variable line with a value before sending it", async () => {
    const { requests } = open();

    await userEvent.click(await screen.findByRole("button", { name: "Add environment" }));
    const dialog = screen.getByRole("dialog", { name: "Add environment" });
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Name" }), "mine");
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "Variable names" }),
      "DB_URL=postgres://x",
    );

    expect(
      within(dialog).getByText("Line 1: only the name. Remove = and what follows."),
    ).toBeVisible();
    await userEvent.click(within(dialog).getByRole("button", { name: "Add environment for me" }));
    expect(requests.some((r) => r.method === "POST")).toBe(false);
  });

  it("shows a refused access under its field", async () => {
    open("/projects/demo/config", {
      [CONFIG]: withEnvironments(),
      [ENV_WRITE]: aProblem({
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
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "Nothing was saved: fix the fields marked below.",
    );
  });

  it("asks to remove the endpoints of an environment still in use first", async () => {
    open("/projects/demo/config", { [CONFIG]: withEnvironments() });

    await userEvent.click(
      await screen.findByRole("button", { name: "Remove environment jane-cloud" }),
    );

    const dialog = screen.getByRole("dialog", { name: /jane-cloud is still used by 1 endpoint$/ });
    expect(within(dialog).getByText(/demo-api › api/)).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Remove 1 endpoint" })).toBeVisible();
  });

  it("confirms before going back to the team's looser access", async () => {
    const { requests } = open("/projects/demo/config", {
      [CONFIG]: withEnvironments(),
      [ENV_WRITE]: withEnvironments(),
    });

    await userEvent.click(
      await screen.findByRole("button", { name: "Use the team's access for staging" }),
    );
    const dialog = screen.getByRole("alertdialog", {
      name: "Use the team's access for staging?",
    });
    expect(within(dialog).getByText(/Your agents may change data in staging again/)).toBeVisible();
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

  it("confirms before removing an endpoint", async () => {
    const { requests } = open("/projects/demo/config", { [CONFIG]: withEnvironments() });

    await userEvent.click(
      await screen.findByRole("button", {
        name: /Edit endpoint of demo-api › api in local: http:\/\/localhost:8000/,
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Remove endpoint" }));

    const dialog = screen.getByRole("alertdialog", {
      name: "Remove the local endpoint of demo-api › api?",
    });
    expect(within(dialog).getByText(/hub.json changes/)).toBeVisible();
    expect(requests.some((r) => r.method === "POST")).toBe(false);
  });

  it("has no serious a11y violations with environments", async () => {
    const { container } = open("/projects/demo/config", { [CONFIG]: withEnvironments() });
    await screen.findByRole("region", { name: /Environments/ });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
