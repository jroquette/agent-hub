import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement } from "react";
import { describe, expect, it, onTestFinished, vi } from "vitest";

import { DiscussProvider } from "../../shell/discuss";
import { seriousViolations } from "../../testing/axe";
import { aCapabilities, aProblem, holdPosts, renderWithApi } from "../../testing/builders";
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
  it("AC-417.6 reads everything agents see about one environment", async () => {
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

  it("AC-417.6 lists the services here by repo, and folds the ones not here yet", async () => {
    const config = aConfig();
    config.environments.services.push({
      repo: "demo-api",
      name: "worker",
      kind: "api",
      description: null,
      endpoints: [],
    });
    open("staging", { [CONFIG]: config });

    expect(
      await screen.findByRole("heading", { level: 2, name: /Services in staging\s*1/ }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Copy the address of demo-api › api in staging" }),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByText("1 service of this project is not here yet"));
    expect(
      screen.getByRole("button", { name: "Open demo-api › worker: not in staging yet" }),
    ).toBeVisible();
  });

  it("AC-417.7 changes the access in place and saves it for the team", async () => {
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

  it("AC-417.7 only lets me make a team environment stricter for myself", async () => {
    open("staging");

    await userEvent.click(
      await screen.findByRole("button", { name: "Change what agents may do in staging" }),
    );
    await userEvent.click(screen.getByRole("radio", { name: /Only me/ }));

    expect(screen.getByRole("radio", { name: "Can change data" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Read only" })).toBeEnabled();
    expect(screen.getByRole("checkbox", { name: /This is production/ })).toBeDisabled();
  });

  it("AC-417.7 saves where the secrets live, by name only", async () => {
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

  it("AC-417.7 shows a refused save under the section and keeps the form open", async () => {
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

  it("AC-417.7 leaves focus on Save through a refused save", async () => {
    open("staging", {
      [WRITE]: aProblem({
        status: 422,
        title: "This change was not saved",
        errors: [{ pointer: "$", message: "hub.json changed since the page read it" }],
      }),
    });
    const held = holdPosts();

    await userEvent.click(
      await screen.findByRole("button", { name: "Change description in staging" }),
    );
    const save = screen.getByRole("button", { name: "Save description" });
    await userEvent.click(save);

    expect(save).toHaveTextContent("Saving…");
    expect(save).toHaveAttribute("aria-disabled", "true");
    expect(save).not.toBeDisabled();
    expect(save).toHaveFocus();
    await userEvent.click(save);
    expect(held.posts()).toBe(1);

    held.release();
    await screen.findByRole("alert");
    expect(document.activeElement).toBe(save);
  });

  it("AC-417.7 Esc in the Discuss panel leaves a section form open; Esc in it cancels", async () => {
    open("staging");
    const panel = document.body.appendChild(document.createElement("aside"));
    panel.className = "ah-discuss";
    const composer = panel.appendChild(document.createElement("textarea"));
    onTestFinished(() => {
      panel.remove();
    });

    await userEvent.click(
      await screen.findByRole("button", { name: "Change description in staging" }),
    );
    const description = screen.getByRole("textbox", { name: "Description" });
    composer.focus();
    await userEvent.keyboard("{Escape}");

    expect(screen.getByRole("textbox", { name: "Description" })).toBe(description);

    description.focus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("textbox", { name: "Description" })).toBeNull();
    expect(screen.getByRole("button", { name: "Change description in staging" })).toBeVisible();
  });

  it("AC-417.5 offers the team's access back on an environment I tightened", async () => {
    open("live");

    expect(await screen.findByRole("button", { name: "Use the team's access" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Remove environment" })).toBeNull();
  });

  it("AC-417.6 says when the environment does not exist", async () => {
    open("stagin");

    expect(await screen.findByText("No environment called stagin")).toBeVisible();
    expect(screen.getByRole("link", { name: "Back to Environments" })).toHaveAttribute(
      "href",
      "/projects/demo/environments",
    );
  });

  it("AC-417.9 sums up what agents read and folds the brief's service lines", async () => {
    open("staging");

    const panel = await screen.findByRole("complementary", { name: "What agents see" });
    expect(within(panel).getByRole("heading", { name: "What your agents read" })).toBeVisible();
    expect(panel).toHaveTextContent("Every session reads this");
    expect(panel).toHaveTextContent("1 service with an address");
    const brief = within(panel).getByText("Show the services as the brief lists them");
    expect(brief.closest("details")).not.toHaveAttribute("open");
    await userEvent.click(brief);
    expect(brief.closest("details")).toHaveAttribute("open");
    expect(within(panel).getByTitle("https://api.staging.example.com")).toBeVisible();
  });

  it("AC-417.10 shows an address whole, its host's end never cut, with a tooltip once cut", async () => {
    let report: () => void = () => undefined;
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          report = callback;
        }
        observe = vi.fn();
        disconnect = vi.fn();
      },
    );
    open("staging");

    const row = await screen.findByRole("button", {
      name: "Open demo-api › api: https://api.staging.example.com in staging",
    });
    expect(row).toHaveTextContent("https://api.staging.example.com");
    expect(row.querySelector(".ah-fit-tail")?.textContent).toBe(
      "https://api.staging.example.com".slice(-18),
    );
    expect(within(row).queryByRole("tooltip")).toBeNull();

    const head = row.querySelector(".ah-fit-head");
    if (!head) throw new Error("no head part");
    Object.defineProperty(head, "scrollWidth", { value: 300 });
    Object.defineProperty(head, "clientWidth", { value: 120 });
    act(() => {
      report();
    });
    expect(within(row).getByRole("tooltip")).toHaveTextContent("https://api.staging.example.com");
    expect(
      screen.getByRole("button", { name: "Copy the address of demo-api › api in staging" }),
    ).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("AC-418.8 offers Find services with Claude before Add service", async () => {
    const { router } = open("staging", {
      "/api/v1/agent-sessions/capabilities": aCapabilities(),
    });

    const head = (await screen.findByRole("heading", { level: 2, name: /Services in staging/ }))
      .parentElement;
    if (!head) throw new Error("no services head");
    const buttons = within(head).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Find services with Claude",
      "Add service",
    ]);
    await userEvent.click(within(head).getByRole("button", { name: "Find services with Claude" }));

    expect(router.state.location.pathname).toBe("/projects/demo/environments/discover");
  });

  it("AC-418.8 turns Find services with Claude off when sessions cannot start", async () => {
    open("staging", {
      "/api/v1/agent-sessions/capabilities": aCapabilities({
        available: false,
        reason: "claude is not on PATH",
      }),
    });

    await screen.findByRole("heading", { level: 2, name: /Services in staging/ });
    expect(await screen.findByRole("button", { name: "Find services with Claude" })).toBeDisabled();
  });

  it("has no serious a11y violations", async () => {
    const { container } = open("staging");
    await screen.findByRole("heading", { level: 1, name: /staging/ });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
