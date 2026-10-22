import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aFeature,
  aFinding,
  aNeedsYouItem,
  anId,
  aPage,
  aProblem,
  aProjectDetail,
  aProjectNow,
  aProjectSummary,
  aRepo,
  aRun,
  aSession,
  aSessionLabel,
  at,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { ProjectOverviewScreen } from ".";

const recent = new Date(Date.now() - 3_600_000).toISOString();
const old = new Date(Date.now() - 30 * 86_400_000).toISOString();

const runs = aPage([
  aRun({
    id: "run-impl",
    stage: "IMPLEMENTING",
    issue: { key: "AGH-112", title: "Cap the tracker team list", url: null },
    cost_usd: "2.1400",
    caps: { budget_usd: "10.0000", max_turns: null, model: null, tracker_transport: null },
  }),
  aRun({
    id: "run-done",
    stage: "REPORTED",
    ended_at: recent,
    pr_url: "https://example.invalid/pr/69",
    issue: { key: "AGH-48", title: "Layered memory", url: null },
  }),
  aRun({
    id: "run-old",
    stage: "REPORTED",
    ended_at: old,
    issue: { key: "AGH-1", title: "Old run", url: null },
  }),
  aRun({
    id: "run-failed",
    stage: "FAILED",
    ended_at: recent,
    failure: { stage: "VERIFYING", reason: "make check exit 2", failing_event_id: null },
    issue: { key: "AGH-79", title: "Guard bypass", url: null },
    steps: [
      {
        attempt: 2,
        ended_at: recent,
        key: "verify",
        max_attempts: 2,
        reason: null,
        session_ids: [],
        started_at: recent,
        status: "failed",
      },
    ],
  }),
]);

function sourced(value: string | null, source: string, where: string) {
  return { value, source, where, team_value: null };
}

function environment(name: string, live = false) {
  return {
    name,
    access: "write",
    production: live,
    description: null,
    credentials: null,
    source: "hub.json",
    team_access: "write",
  };
}

const commitTitle = {
  pattern: "{ISSUE}: {type}({scope}): {summary}",
  source: "project",
  where: "hub.json → project.conventions.commit_title",
  example: "TIP-42: feat(api): add the hub config view",
};

const hubConfig = {
  project: "agent-hub",
  hub_path: "/hubs/agent-hub",
  hub_repo: "acme/agent-hub",
  team_file: { name: "hub.json", path: "/hubs/agent-hub/hub.json", problems: [] },
  local_file: { name: "hub.local.json", path: "/hubs/agent-hub/hub.local.json", problems: [] },
  author_name: sourced("Jane Doe", "local", "hub.local.json → project.author_name"),
  author_email: sourced(null, "default", "built-in default"),
  branch_prefix: sourced("jdoe/", "local", "hub.local.json → project.branch_prefix"),
  default_branch: sourced("main", "default", "built-in default (main)"),
  conventions: [
    {
      pattern: "{ISSUE}-{slug}",
      source: "project",
      where: "hub.json → project.conventions.branch",
      example: "TIP-42-hub-config",
    },
    commitTitle,
    { ...commitTitle, source: "commit_title", where: "follows the commit title" },
  ],
  repos: [
    {
      index: 0,
      dir: "demo-api",
      github: "acme/demo-api",
      role: "app",
      default_branch: sourced("main", "default", "built-in default (main)"),
      branch: commitTitle,
      commit_title: commitTitle,
      pr_title: commitTitle,
      check_fast: "make check-fast",
      check_fast_timeout: 120,
      check: "make check",
    },
  ],
  tracker: {
    kind: "linear",
    teams: ["TIP"],
    transport: sourced("api", "default", "built-in default (api)"),
    ready_label: "agent-ready",
    failed_label: "agent-failed",
    blocked_label: null,
    started_state: "In Progress",
    review_state: "In Review",
    team_set: [],
  },
  guard: {
    blocked_words: { team: ["acme-secret"], local: ["my-client"] },
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
  modules: ["bench", "cloud"],
  platform_version: "0.4.0",
  environments: {
    environments: [environment("local"), environment("shared", true)],
    services: [],
    blocked_words: [],
    blocked_files: [],
    blocked_env: [],
  },
};

const routes: ApiRoutes = {
  "/api/v1/projects/agent-hub/config": hubConfig,
  "/api/v1/projects/agent-hub": aProjectDetail({
    lock_state: "sync_pending",
    lock_version: "0.3.0",
    modules: ["bench", "cloud"],
    warnings: ["pinned 0.4.0, running 0.5.0"],
  }),
  "/api/v1/projects/agent-hub/now": aProjectNow({
    watch: [
      { text: "Bench stderr test is flaky", last_verified: "2026-01-01", provenance: "agent" },
    ],
  }),
  "/api/v1/projects/agent-hub/repos": aPage([
    aRepo(),
    aRepo({ name: "docs", agents_md_present: false, agents_md_lines: null }),
    aRepo({ name: "big", agents_md_lines: 132 }),
  ]),
  "/api/v1/projects": aPage([aProjectSummary()]),
  "/api/v1/workflow-runs": runs,
  "/api/v1/features": aPage([
    aFeature({ slug: "control-plane", issues: ["ACME-1511"] }),
    aFeature({ slug: "old-feature", issues: ["ACME-1"] }),
  ]),
  "/api/v1/feature-names": aPage([]),
  "/api/v1/sessions": aPage([
    aSession({
      id: anId(1),
      status: "ended",
      outcome: "error",
      errors: 6,
      started_at: at(-9000),
      ended_at: at(-6000),
      last_activity_at: recent,
      agent: "main",
      label: aSessionLabel({ issue: "ACME-1511", repo: "storefront", branch: "main" }),
    }),
    aSession({
      id: anId(2),
      status: "live",
      label: aSessionLabel({ issue: null, workflow: "/create-plan", branch: "dev/agh-9-x" }),
      started_at: at(-100),
      last_activity_at: recent,
    }),
    aSession({
      id: anId(3),
      status: "ended",
      outcome: "done",
      last_activity_at: recent,
      label: aSessionLabel({
        issue: "ACME-7",
        title: "Fix the order export",
        workflow: "/fix",
        workflows: ["/fix"],
      }),
    }),
    aSession({
      id: anId(4),
      status: "live",
      last_activity_at: recent,
      label: aSessionLabel({ issue: "AGH-112", workflow: "/fix", workflows: ["/fix"] }),
    }),
    aSession({
      id: anId(5),
      status: "ended",
      outcome: "done",
      last_activity_at: old,
      label: aSessionLabel({ issue: "ACME-1", workflow: "/feature", workflows: ["/feature"] }),
    }),
  ]),
  "/api/v1/needs-you": aPage([
    aNeedsYouItem({
      verb: "Approve the plan",
      context: "agent-hub · AGH-131 · Doctor JSON output",
      href: "/sessions/s-plan",
    }),
  ]),
  "/api/v1/doctor/findings": aPage([
    aFinding({
      severity: "warning",
      rule: "brain.memory",
      path: ".gitignore",
      line: null,
      message: "no line ignoring brain/auto/workspace/",
    }),
    aFinding({
      severity: "error",
      rule: "instructions.size",
      path: "AGENTS.md",
      line: 1,
      message: "132 lines, limit 100",
    }),
  ]),
};

function renderProject(overrides: ApiRoutes = {}, name = "agent-hub") {
  return renderWithApi(<ProjectOverviewScreen />, {
    routes: { ...routes, ...overrides },
    path: `/projects/${name}`,
    route: "/projects/:project",
  });
}

describe("ProjectOverviewScreen", () => {
  it("shows the header with setup status, a plain summary and warnings", async () => {
    renderProject();

    expect(await screen.findByRole("heading", { level: 1, name: "agent-hub" })).toBeInTheDocument();
    expect(await screen.findByText("Setup · 1 error, 1 warning")).toBeInTheDocument();
    expect(await screen.findByText(/running now/)).toHaveTextContent(
      "1 agent session running now, 1 ticket being worked on, 1 ticket stopped with a problem this week. Linear team AGH · 1 repository.",
    );
    expect(screen.getByText("pinned 0.4.0, running 0.5.0")).toBeInTheDocument();
  });

  it("lists what needs you first, linking to the approval", async () => {
    renderProject();

    const needs = await screen.findByRole("region", { name: /Needs you/ });
    expect(within(needs).getByRole("link", { name: /Approve the plan/ })).toHaveAttribute(
      "href",
      "/sessions/s-plan",
    );
  });

  it("AC-273.11: shows four needs and a See N more line past them", async () => {
    renderProject({
      "/api/v1/needs-you": aPage(
        Array.from({ length: 6 }, (_, i) =>
          aNeedsYouItem({ verb: `Answer question ${String(i)}`, href: `/sessions/s${String(i)}` }),
        ),
      ),
    });

    const needs = await screen.findByRole("region", { name: /Needs you/ });
    expect(await within(needs).findAllByRole("link", { name: /Answer question/ })).toHaveLength(4);
    expect(within(needs).getByRole("link", { name: /See 2 more/ })).toBeInTheDocument();
  });

  it("AC-273.14: says no agent is working when only finished tickets are left", async () => {
    renderProject({
      "/api/v1/workflow-runs": aPage([
        aRun({
          id: "run-done",
          stage: "REPORTED",
          ended_at: recent,
          pr_url: null,
          issue: { key: "AGH-48", title: "Layered memory", url: null },
        }),
      ]),
    });

    const work = await screen.findByRole("region", { name: "Tickets the agents are working on" });
    expect(await within(work).findByText(/Here is what finished this week/)).toBeInTheDocument();
    expect(within(work).getByText("Finished without a pull request")).toBeInTheDocument();
    expect(within(work).getByText("Done")).toBeInTheDocument();
  });

  it("shows this week's numbers with the cost delta", async () => {
    renderProject();

    expect(await screen.findByText("$10.50")).toBeInTheDocument();
    expect(screen.getByText("+31.3 %")).toBeInTheDocument();
    expect(screen.getByText("vs $8.00 the week before")).toBeInTheDocument();
    expect(screen.getByText("last 7 days · 1 stopped")).toBeInTheDocument();
  });

  it("shows the focus cards and marks one not checked for over 60 days", async () => {
    renderProject();

    const watch = await screen.findByRole("article", { name: "Watch out for" });
    expect(within(watch).getByText("Bench stderr test is flaky")).toBeInTheDocument();
    expect(within(watch).getByText(/^Not checked for \d+ days$/)).toBeInTheDocument();
    expect(
      within(screen.getByRole("article", { name: "Focus now" })).queryByText(/Not checked/),
    ).not.toBeInTheDocument();
  });

  it("lists the agents' tickets in progress first, then stopped, then done this week", async () => {
    renderProject();

    const work = await screen.findByRole("region", { name: "Tickets the agents are working on" });
    await within(work).findByText("Cap the tracker team list");
    const titles = within(work)
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"));
    expect(titles).toEqual([
      "/runs?project=agent-hub",
      "/runs/run-impl",
      "/runs/run-failed",
      "/runs/run-done",
    ]);
    expect(within(work).queryByText("Old run")).not.toBeInTheDocument();
    expect(within(work).getByText("Building · step 3 of 6")).toBeInTheDocument();
    expect(within(work).getByText("Stopped while testing")).toBeInTheDocument();
    expect(within(work).getByText("Problem: make check exit 2")).toBeInTheDocument();
    expect(within(work).getByText("Pull request opened")).toBeInTheDocument();
  });

  it("says plainly when no agent is working on a ticket", async () => {
    renderProject({ "/api/v1/workflow-runs": aPage([]) });

    expect(
      await screen.findByText("No agent is working on a ticket right now."),
    ).toBeInTheDocument();
  });

  it("AC-273.15 lists the features worked on this week, never sessions, and opens one on click", async () => {
    const user = userEvent.setup();
    const { router } = renderProject();

    const recent = await screen.findByRole("region", { name: "Recent work" });
    const features = within(await within(recent).findByRole("list", { name: "Features" }));
    expect(await features.findByText("control-plane")).toBeInTheDocument();
    expect(features.queryByText("old-feature")).not.toBeInTheDocument();
    expect(within(recent).queryByRole("table")).not.toBeInTheDocument();
    await user.click(features.getByText("control-plane"));
    expect(router.state.location.pathname).toBe("/features/agent-hub/control-plane");
  });

  it("AC-273.15 lists the tickets worked on this week, leaving out the agents' own runs", async () => {
    const user = userEvent.setup();
    const { router } = renderProject();

    const recent = await screen.findByRole("region", { name: "Recent work" });
    const tickets = within(await within(recent).findByRole("list", { name: "Tickets" }));
    expect(await tickets.findByText("ACME-7")).toBeInTheDocument();
    expect(tickets.getByText("Fix the order export")).toBeInTheDocument();
    // AGH-112 runs as an agent ticket, already listed above.
    expect(tickets.queryByText("AGH-112")).not.toBeInTheDocument();
    // ACME-1511 belongs to a feature.
    expect(tickets.queryByText("ACME-1511")).not.toBeInTheDocument();
    await user.click(tickets.getByText("ACME-7"));
    expect(router.state.location.pathname).toBe(`/sessions/${anId(3)}`);
  });

  it("AC-273.16 folds setup and health away for engineers, with findings, repos and the hub", async () => {
    const user = userEvent.setup();
    renderProject();

    const setup = (await screen.findByText("Setup and health")).closest("details");
    expect(setup).not.toHaveAttribute("open");
    expect(await within(setup as HTMLElement).findByText("2 things to fix")).toBeInTheDocument();
    await user.click(screen.getByText("Setup and health"));
    expect(setup).toHaveAttribute("open");

    const scope = within(setup as HTMLElement);
    expect(await scope.findByText("1 error · 1 warning · 0 info")).toBeInTheDocument();
    expect(scope.getByRole("link", { name: /See all 2 findings/ })).toBeInTheDocument();
    // The message leads; the rule id follows as a reference.
    expect(scope.getByText("132 lines, limit 100")).toBeInTheDocument();
    const rules = scope.getAllByText(/instructions\.size|brain\.memory/).map((n) => n.textContent);
    expect(rules).toEqual(["instructions.size", "brain.memory"]);

    const table = scope.getByRole("table", { name: "Repos" });
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(headers).toEqual([
      "Repo",
      "What it is",
      "Main branch",
      "Open pull requests",
      "Checks",
      "Agent instructions",
    ]);
    // The commands live in each Checks tooltip, not in a cell of their own.
    expect(within(table).queryAllByRole("button", { name: /Copy/ })).toHaveLength(0);
    expect(within(table).getAllByText("Fast and full")).toHaveLength(3);
    expect(within(table).getByText("Missing")).toBeInTheDocument();
    expect(within(table).getByText("132 lines, over 100")).toBeInTheDocument();
  });

  it("AC-427.18 says how the project is set up in sentences, never as a made-up example", async () => {
    renderProject();

    const section = within(
      await screen.findByRole("region", { name: "How this project is set up" }),
    );
    expect(await section.findByText("Sync pending (lock 0.3.0, pin 0.4.0)")).toBeInTheDocument();
    expect(section.getByText(/Agents pick up Linear issues in team/)).toBeInTheDocument();
    expect(section.getByText("agent-ready")).toBeInTheDocument();
    // Patterns read as words; the made-up example only sits in a tooltip.
    const examples = section.getAllByText(/TIP-42/);
    expect(examples.length).toBeGreaterThan(0);
    for (const example of examples) expect(example.closest('[role="tooltip"]')).not.toBeNull();
    expect(section.getAllByText(/Example with a made-up issue/).length).toBe(2);
    expect(section.getByText("Commit and pull request titles")).toBeInTheDocument();
    expect(section.getAllByText("issue key").length).toBeGreaterThan(0);
    expect(section.getByText("short description")).toBeInTheDocument();
    // The pattern has no {prefix}, so the prefix is said to be unused.
    expect(section.getByText(/is not used: the branch pattern has no place/)).toBeInTheDocument();
    expect(section.getAllByText("Set by you").length).toBeGreaterThan(0);
    expect(section.queryByText("Built-in")).not.toBeInTheDocument();
    // Guard rules as sentences; a rule with nothing in it is not shown.
    expect(
      section.getByText("Agents ask you before editing 1 file or folder."),
    ).toBeInTheDocument();
    expect(
      section.getByText("2 words are blocked from anything the agents write."),
    ).toBeInTheDocument();
    expect(section.queryByText(/never contact/)).not.toBeInTheDocument();
    // What agents may do in each environment (AGH-416's config view), the live one badged.
    expect(section.getByText("Production")).toBeInTheDocument();
    expect(section.getByText("1 repository: demo-api.")).toBeInTheDocument();
    expect(section.getByRole("link", { name: /Open hub configuration/ })).toHaveAttribute(
      "href",
      "/projects/agent-hub/config",
    );
    expect(section.getByRole("link", { name: /See guard/ })).toHaveAttribute(
      "href",
      "/projects/agent-hub/config#guard",
    );
  });

  it("AC-273.16 links Repositories to the hub configuration once, with no per-repo link", async () => {
    const user = userEvent.setup();
    renderProject();

    await user.click(await screen.findByText("Setup and health"));
    const setup = within(screen.getByText("Setup and health").closest("details") as HTMLElement);
    expect(setup.getAllByRole("link", { name: /Open hub configuration/ })).toHaveLength(1);
    expect(setup.queryByRole("link", { name: /Conventions of/ })).not.toBeInTheDocument();
  });

  it("AC-427.20 opens the folded Setup and health when the header's setup badge is followed", async () => {
    const user = userEvent.setup();
    renderProject();

    const setup = (await screen.findByText("Setup and health")).closest("details");
    expect(setup).not.toHaveAttribute("open");
    await user.click(await screen.findByText("Setup · 1 error, 1 warning"));
    expect(setup).toHaveAttribute("open");
  });

  it("AC-427.21 moves across the recent rows with j and k", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    const user = userEvent.setup();
    renderProject();

    const recent = await screen.findByRole("region", { name: "Recent work" });
    const features = await within(recent).findByRole("list", { name: "Features" });
    await within(features).findByText("control-plane");
    const tickets = await within(recent).findByRole("list", { name: "Tickets" });
    await within(tickets).findByText("ACME-7");
    const rows = [...recent.querySelectorAll<HTMLElement>("[data-nav-row]")];
    expect(rows.length).toBeGreaterThan(1);
    await user.keyboard("j");
    expect(rows[0]).toHaveFocus();
    await user.keyboard("j");
    expect(rows[1]).toHaveFocus();
    await user.keyboard("k");
    expect(rows[0]).toHaveFocus();
  });

  it("AC-427.18 puts a pattern's made-up example in a tooltip the keyboard reaches", async () => {
    renderProject();

    const section = await screen.findByRole("region", { name: "How this project is set up" });
    await within(section).findByText("Commit and pull request titles");
    const hints = [...section.querySelectorAll<HTMLElement>(".po-hint")];
    expect(hints.length).toBeGreaterThan(0);
    // The shared Tooltip opens on focus within its wrapper, so a Tab stop on the text reaches it.
    for (const hint of hints) expect(hint).toHaveAttribute("tabindex", "0");
    const tips = hints.map((hint) => hint.parentElement?.querySelector('[role="tooltip"]'));
    expect(tips.map((tip) => tip?.textContent)).toEqual(
      expect.arrayContaining([expect.stringMatching(/^Example with a made-up issue: TIP-42/)]),
    );
    // The ask-before-edit paths are a mono list in their tooltip.
    expect(tips.some((tip) => tip?.querySelector(".po-path-list code") != null)).toBe(true);
  });

  describe("states", () => {
    it("shows the header skeleton after 300 ms while pending", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        renderProject({ "/api/v1/projects/agent-hub": "pending" });
        await act(async () => {
          await vi.advanceTimersByTimeAsync(350);
        });
        expect(document.querySelectorAll(".ah-skel").length).toBeGreaterThan(3);
      } finally {
        vi.useRealTimers();
      }
    });

    it("shows each section's empty copy when the project has no activity", async () => {
      renderProject({
        "/api/v1/projects/agent-hub/now": aProjectNow({ focus: [], next: [], watch: [] }),
        "/api/v1/workflow-runs": aPage([]),
        "/api/v1/needs-you": aPage([]),
        "/api/v1/sessions": aPage([]),
        "/api/v1/doctor/findings": aPage([]),
        "/api/v1/projects": aPage([]),
      });

      expect(await screen.findByText("No current focus recorded")).toBeInTheDocument();
      expect(await screen.findByText("Nothing needs you.")).toBeInTheDocument();
      expect(
        await screen.findByText("No agent is working on a ticket right now."),
      ).toBeInTheDocument();
      expect(await screen.findByText("No sessions yet.")).toBeInTheDocument();
      expect(screen.getByText("cd /home/dev/agent-hub-hub && claude")).toBeInTheDocument();
      expect(await screen.findByText("No findings.")).toBeInTheDocument();
      expect(await screen.findByText("Setup · all good")).toBeInTheDocument();
    });

    it("keeps a failing section's problem inside it", async () => {
      renderProject({
        "/api/v1/workflow-runs": aProblem({ status: 503, title: "Busy", detail: "Database busy." }),
      });

      expect(await screen.findByText("Could not load the agents' tickets")).toBeInTheDocument();
      expect(screen.getByText("Database busy.")).toBeInTheDocument();
      expect(await screen.findByRole("list", { name: "Features" })).toBeInTheDocument();
    });

    it("AC-427.19 keeps a failing features read inside its column", async () => {
      renderProject({
        "/api/v1/features": aProblem({ status: 503, title: "Busy", detail: "Records busy." }),
      });

      expect(await screen.findByText("Could not load features")).toBeInTheDocument();
      expect(await screen.findByRole("list", { name: "Tickets" })).toBeInTheDocument();
    });

    it("AC-427.19 says which features were worked on is unknown when sessions fail", async () => {
      renderProject({
        "/api/v1/sessions": aProblem({ status: 503, title: "Busy", detail: "Sessions busy." }),
      });

      expect(
        await screen.findByText("Could not tell which features were worked on"),
      ).toBeInTheDocument();
      expect(screen.getByText("Could not load tickets")).toBeInTheDocument();
      expect(screen.queryByText("No feature was worked on in the last 7 days.")).toBeNull();
    });

    it("shows the now.md problem when the file cannot be read", async () => {
      renderProject({
        "/api/v1/projects/agent-hub/now": aProjectNow({
          problem: "brain/now.md is not valid UTF-8.",
        }),
      });

      expect(await screen.findByText("brain/now.md is not valid UTF-8.")).toBeInTheDocument();
    });

    it("shows Project not found for an unknown project", async () => {
      renderProject(
        { "/api/v1/projects/agent-hb": aProblem({ status: 404, title: "Not found" }) },
        "agent-hb",
      );

      expect(await screen.findByRole("heading", { name: "Project not found" })).toBeInTheDocument();
      expect(
        screen.getByText("No registered hub has a project named agent-hb."),
      ).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Go to Portfolio" })).toHaveAttribute("href", "/");
    });

    it("shows the problem when the project cannot be read", async () => {
      const user = userEvent.setup();
      const { requests } = renderProject({
        "/api/v1/projects/agent-hub": aProblem({
          status: 500,
          title: "Internal error",
          detail: "hub.json unreadable",
        }),
      });

      expect(await screen.findByText("Could not load this project")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Try again" }));
      await waitFor(() => {
        expect(requests.filter((r) => r.url.endsWith("/projects/agent-hub")).length).toBe(2);
      });
    });

    it("stamps the header as stale when the collector is offline", async () => {
      renderProject();

      await screen.findByRole("heading", { level: 1, name: "agent-hub" });
      expect(screen.getByText(/^Stale · as of/)).toBeInTheDocument();
    });
  });

  it("AC-427.23 has no serious a11y violations (a11y)", async () => {
    const { container } = renderProject();

    await screen.findByText("Cap the tracker team list");
    await screen.findByText("ACME-7");
    await screen.findByText("control-plane");
    expect(await seriousViolations(container)).toEqual([]);
  });
  it("calls a scenario run 'Scenario run …' in Work in flight and links its page", async () => {
    renderProject({
      "/api/v1/workflow-runs": aPage([
        aRun({
          id: "3f2a91c0",
          project: "agent-hub",
          workflow: "scenario:order-lifecycle",
          kind: "scenario",
          issue: null,
          stage: "PICKED",
          ended_at: null,
          started_at: recent,
        }),
      ]),
    });

    const work = await screen.findByRole("region", { name: "Tickets the agents are working on" });
    const link = await within(work).findByRole("link", { name: /Scenario run 3f2a91c0/ });
    expect(link).toHaveAttribute("href", "/scenarios/agent-hub/order-lifecycle/runs/3f2a91c0");
    expect(link).toHaveTextContent("order-lifecycle");
    expect(within(work).queryByText(/^Run 3f2a91c0/)).toBeNull();
  });
  it("gives a scenario run in Work in flight its own status, with no stages or pull request", async () => {
    renderProject({
      "/api/v1/workflow-runs": aPage([
        aRun({
          id: "3f2a91c0",
          project: "agent-hub",
          workflow: "scenario:order-lifecycle",
          kind: "scenario",
          issue: null,
          stage: "REPORTED",
          status: "done",
          started_at: recent,
          ended_at: recent,
          pr_url: null,
        }),
      ]),
    });

    const work = await screen.findByRole("region", { name: "Tickets the agents are working on" });
    const link = await within(work).findByRole("link", { name: /Scenario run 3f2a91c0/ });
    expect(link).toHaveTextContent("Done");
    expect(link).not.toHaveTextContent(/pull request/i);
    expect(link.querySelector(".po-steps")).toBeNull();
  });
});
