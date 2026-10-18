import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement } from "react";
import { describe, expect, it } from "vitest";

import { DiscussProvider, useDiscuss } from "../../shell/discuss";
import { seriousViolations } from "../../testing/axe";
import { aProblem, renderWithApi, type ApiRoutes } from "../../testing/builders";
import { HubConfigScreen } from "./index";

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
    agent_models: [],
    modules: ["cloud"],
    platform_version: "0.2.0",
    ...overrides,
  };
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
  it("shows each repo's default branch and commit pattern with its source and an example", async () => {
    open();

    const repos = await screen.findByRole("region", { name: /Repositories/ });
    expect(within(repos).getByText("develop")).toBeVisible();
    expect(within(repos).getAllByText("{type}({scope}): {summary} ({ISSUE})")[0]).toBeVisible();
    expect(
      within(repos).getAllByText("feat(api): add the hub config view (DEM-42)")[0],
    ).toBeVisible();
    expect(within(repos).getAllByText("Team · repo")[0]).toBeVisible();
    expect(within(repos).getByText("Same as the commit title")).toBeVisible();
  });

  it("says who commits and which layer set it", async () => {
    open();

    const who = await screen.findByRole("region", { name: /Who commits/ });
    expect(within(who).getByText("me@example.com")).toBeVisible();
    expect(within(who).getByText("Local")).toBeVisible();
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
    expect(within(guard).getByText("1 team · 1 yours")).toBeVisible();
    await userEvent.click(
      within(guard).getByRole("button", { name: "Ask Claude to change blocked words" }),
    );
    expect(screen.getByRole("list", { name: "references" })).not.toHaveTextContent("acme-prod");
    await userEvent.click(within(guard).getByRole("button", { name: "Show words" }));
    expect(within(guard).getByText("acme-prod")).toBeVisible();
  });

  it("shows the team's value under the Team layer even where the local one wins", async () => {
    open("/projects/demo/config?layer=team");

    const who = await screen.findByRole("region", { name: /Who commits/ });
    expect(within(who).getByText("jane@example.com")).toBeVisible();
    expect(within(who).getByText(/Your local value applies/)).toHaveTextContent("me@example.com");
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

    await userEvent.click(await screen.findByRole("button", { name: "Edit my local settings" }));
    const dialog = screen.getByRole("dialog", { name: "Edit my local settings" });
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Branch prefix" }), "nope");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save local settings" }));

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

    await userEvent.click(await screen.findByRole("button", { name: "Edit my local settings" }));
    const dialog = screen.getByRole("dialog", { name: "Edit my local settings" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Save local settings" }));

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

    await userEvent.click(await screen.findByRole("button", { name: "Edit my local settings" }));
    await userEvent.click(screen.getByRole("button", { name: "Save local settings" }));

    expect(await screen.findByText("Saved hub.local.json")).toBeVisible();
  });

  it("explains a hub.json it cannot read", async () => {
    open("/projects/demo/config", {
      [CONFIG]: aProblem({ status: 404, title: "Project not found", detail: "No project demo." }),
    });

    expect(await screen.findByText("Project not found")).toBeVisible();
  });

  it("has no serious a11y violations", async () => {
    const { container } = open();
    await screen.findByRole("region", { name: /Repositories/ });
    await waitFor(async () => {
      expect(await seriousViolations(container)).toEqual([]);
    });
  });
});
