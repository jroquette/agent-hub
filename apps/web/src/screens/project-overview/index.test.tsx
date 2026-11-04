import { timeoutManager } from "@tanstack/react-query";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { apiKey, createQueryClient } from "../../lib/api";
import { SCREEN_READ_TIMEOUT_MS } from "../../lib/screenRead";
import { AppShell } from "../../shell/AppShell";
import { GlobalStreamProvider } from "../../shell/GlobalStream";
import { seriousViolations } from "../../testing/axe";
import {
  aDoctorFindings,
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
  aShellView,
  aStreamCounts,
  at,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { ProjectOverviewScreen } from ".";
import { codeText } from "../../testing/text";

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
  "/api/v1/doctor/findings": aDoctorFindings([
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

const OVERVIEW_READ = "/api/v1/screens/project-overview/agent-hub";

/** The routes whose answers the overview read (ADR 0056) carries. */
const overviewResources = [
  "/api/v1/projects/agent-hub",
  "/api/v1/doctor/findings",
  "/api/v1/projects",
  "/api/v1/needs-you",
  "/api/v1/workflow-runs",
  "/api/v1/projects/agent-hub/now",
  "/api/v1/features",
  "/api/v1/projects/agent-hub/repos",
  "/api/v1/projects/agent-hub/config",
  "/api/v1/sessions",
];

/** The sessions of the issues worked on this week: a feature's (ACME-1511) and a ticket's. */
const weekSessions = aPage([
  aSession({
    id: anId(11),
    status: "ended",
    outcome: "done",
    last_activity_at: recent,
    label: aSessionLabel({ issue: "ACME-1511", repo: "storefront", branch: "main" }),
  }),
  aSession({
    id: anId(13),
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
]);

/** The overview read of `agent-hub`: each region's part as `routes` answers it, and this week's
 * sessions. */
function anOverviewRead(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    project: routes["/api/v1/projects/agent-hub"],
    findings: routes["/api/v1/doctor/findings"],
    projects: routes["/api/v1/projects"],
    needs_you: routes["/api/v1/needs-you"],
    runs: routes["/api/v1/workflow-runs"],
    now: routes["/api/v1/projects/agent-hub/now"],
    features: routes["/api/v1/features"],
    repos: routes["/api/v1/projects/agent-hub/repos"],
    config: routes["/api/v1/projects/agent-hub/config"],
    recent_sessions: weekSessions,
    has_sessions: true,
    ...overrides,
  };
}

/** Renders the screen from its overview read, every resource route answered too, on the app's own
 * query client: under its 10 s staleTime a seeded query does not fetch. */
function renderFromRead(
  read: Record<string, unknown>,
  overrides: ApiRoutes = {},
  queryClient = createQueryClient(),
) {
  return renderWithApi(<ProjectOverviewScreen />, {
    routes: { ...routes, [OVERVIEW_READ]: read, ...overrides },
    path: "/projects/agent-hub",
    route: "/projects/:project",
    queryClient,
  });
}

/** The project's newest 200 sessions, the one cache entry the Tickets screen reads whole. */
const sharedSessionsKey = apiKey("/api/v1/sessions", {
  query: { project: "agent-hub", limit: 200, sort: "-last_activity_at" },
});

/** Where the overview keeps its last read for the next visit: under the read's own key. */
const keptOverviewKey = apiKey("/api/v1/screens/project-overview/{project}", {
  path: { project: "agent-hub" },
});

/** A session on ACME-99, a ticket an agent worked on after the first visit's read. */
const acme99Session = aSession({
  id: anId(21),
  status: "ended",
  outcome: "done",
  last_activity_at: recent,
  label: aSessionLabel({ issue: "ACME-99", workflow: "/fix", workflows: ["/fix"] }),
});

/** From now on, holds each request to `path` until `release()`. `asked()` counts them, held or
 * not: `calls()` records a request only once the stub answers it. */
function holdRequests(path: string): { release: () => void; asked: () => number } {
  const answer = vi.mocked(globalThis.fetch).getMockImplementation();
  if (answer === undefined) throw new Error("fetch is not stubbed");
  let release: () => void = () => undefined;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let asked = 0;
  vi.mocked(globalThis.fetch).mockImplementation(async (input, init) => {
    const url = input instanceof Request ? input.url : String(input);
    if (new URL(url, window.location.origin).pathname === path) {
      asked += 1;
      await held;
    }
    return answer(input, init);
  });
  return {
    release: () => {
      release();
    },
    asked: () => asked,
  };
}

/** TanStack Query's default gcTime, which `createQueryClient` keeps: an entry nothing observes is
 * dropped 5 min after its removal timer starts. */
const GC_TIME = 5 * 60_000;

/**
 * Time passing for the query cache. `pass(ms)` moves the faked Date `ms` on (fake it first) and
 * runs each of TanStack Query's removal timers due by then; its other timers run as usual.
 */
function aRemovalClock(): { pass: (ms: number) => void } {
  const setTimer = timeoutManager.setTimeout.bind(timeoutManager);
  const clearTimer = timeoutManager.clearTimeout.bind(timeoutManager);
  const due = new Map<number, { at: number; run: () => void }>();
  let now = 0;
  let lastId = 0;
  vi.spyOn(timeoutManager, "setTimeout").mockImplementation((callback, delay) => {
    if (delay !== GC_TIME) return setTimer(callback, delay);
    lastId -= 1;
    due.set(lastId, {
      at: now + delay,
      run: () => {
        callback();
      },
    });
    return lastId;
  });
  vi.spyOn(timeoutManager, "clearTimeout").mockImplementation((id) => {
    if (typeof id === "number" && due.has(id)) due.delete(id);
    else clearTimer(id);
  });
  return {
    pass: (ms) => {
      vi.setSystemTime(Date.now() + ms);
      now += ms;
      for (const [id, timer] of [...due]) {
        if (timer.at > now) continue;
        due.delete(id);
        timer.run();
      }
    },
  };
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
    expect(router.state.location.pathname).toBe("/tickets/agent-hub/ACME-7");
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
        "/api/v1/doctor/findings": aDoctorFindings([]),
        "/api/v1/projects": aPage([]),
      });

      expect(await screen.findByText("No current focus recorded")).toBeInTheDocument();
      expect(await screen.findByText("Nothing needs you.")).toBeInTheDocument();
      expect(
        await screen.findByText("No agent is working on a ticket right now."),
      ).toBeInTheDocument();
      expect(await screen.findByText("No sessions yet.")).toBeInTheDocument();
      expect(
        screen.getByText(codeText("cd /home/dev/agent-hub-hub && claude")),
      ).toBeInTheDocument();
      // AC-596.5.19: the command is coloured as shell, not only found by its text.
      const command = screen.getByText(codeText("cd /home/dev/agent-hub-hub && claude"));
      await waitFor(() => {
        expect(command).toHaveClass("hljs");
      });
      expect(command.querySelector("span[class^='hljs-']")).not.toBeNull();
      expect(await screen.findByText("No findings.")).toBeInTheDocument();
      expect(await screen.findByText("Setup · all good")).toBeInTheDocument();
    });

    it("says the hub is not checked yet, not set up, until its first check ends", async () => {
      renderProject({
        "/api/v1/projects/agent-hub": aProjectDetail({ checked_at: null }),
        "/api/v1/projects": aPage([aProjectSummary({ checked_at: null, hub_health: null })]),
        "/api/v1/doctor/findings": aDoctorFindings([], { checked_at: null }),
      });

      const title = await screen.findByRole("heading", { level: 1, name: "agent-hub" });
      const header = title.closest("header");
      if (!header) throw new Error("no header");
      await waitFor(() => {
        expect(within(header).queryByText(/^Setup ·|^Not checked$/)).not.toBeNull();
      });
      expect(within(header).queryByText(/^Setup ·/)).toBeNull();
      // Portfolio's badge for a hub the doctor has not checked: idle, "Not checked".
      expect(within(header).getByText("Not checked")).toHaveClass("ah-badge", "ah-badge-idle");
      // Named as on Portfolio, so it says what was not checked.
      const health = within(header).getByRole("img", {
        name: "Health: doctor has not run for this hub",
      });
      expect(health).toContainElement(within(header).getByText("Not checked"));
      const block = screen.getByRole("heading", { name: "Health checks" }).parentElement
        ?.parentElement;
      if (!block) throw new Error("no Health checks block");
      // Spec 12's "Health: never run" note, without its run-it-yourself step.
      expect(within(block).getByText("Doctor has not run for this hub.")).toBeInTheDocument();
      expect(block).not.toHaveTextContent(/hub doctor/);
      expect(block).not.toHaveTextContent("No findings.");
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

  it("reads the findings again until the first check ends", async () => {
    vi.useFakeTimers();
    try {
      // AGH-608: the hub's first background check may not have ended when the page opens.
      let answers = 0;
      const { requests } = renderProject({
        "/api/v1/doctor/findings": () => {
          answers += 1;
          return aDoctorFindings([aFinding({ severity: "error", rule: "instructions.size" })], {
            checked_at: answers === 1 ? null : at(0),
          });
        },
      });
      const findingsReads = () =>
        requests.filter((r) => new URL(r.url).pathname === "/api/v1/doctor/findings").length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByRole("heading", { level: 1, name: "agent-hub" })).toBeInTheDocument();
      expect(findingsReads()).toBe(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      expect(findingsReads()).toBe(2);

      // The check has ended: no more reads.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
      });
      expect(findingsReads()).toBe(2);
    } finally {
      vi.useRealTimers();
    }
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

  it("AC-36 loads in at most 5 API requests with the shell mounted", async () => {
    // The app's own query client: under its 10 s staleTime a seeded query does not fetch.
    const { calls } = renderWithApi(
      <AppShell>
        <ProjectOverviewScreen />
      </AppShell>,
      {
        routes: {
          "/api/v1/screens/shell": aShellView(),
          [OVERVIEW_READ]: anOverviewRead(),
          "/api/v1/feature-names": aPage([]),
        },
        path: "/projects/agent-hub",
        route: "/projects/:project",
        queryClient: createQueryClient(),
      },
    );

    // Each region shows its part of the overview read; feature names stay their own call.
    expect(await screen.findByRole("heading", { level: 1, name: "agent-hub" })).toBeInTheDocument();
    expect(await screen.findByText("Setup · 1 error, 1 warning")).toBeInTheDocument();
    expect(await screen.findByText("Cap the tracker team list")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /Approve the plan/ })).toBeInTheDocument();
    expect(await screen.findByText("Bench stderr test is flaky")).toBeInTheDocument();
    const recentWork = await screen.findByRole("region", { name: "Recent work" });
    expect(await within(recentWork).findByText("control-plane")).toBeInTheDocument();
    expect(await within(recentWork).findByText("ACME-7")).toBeInTheDocument();
    const asked = calls();
    expect(asked.filter((path) => overviewResources.includes(path))).toEqual([]);
    expect(asked.filter((path) => path === OVERVIEW_READ)).toHaveLength(1);
    expect(asked.length).toBeLessThanOrEqual(5);
  });

  it("shows recent work from the overview read's sessions", async () => {
    // The sessions route lists another ticket: a screen that read it would show ACME-99.
    const { calls } = renderFromRead(anOverviewRead(), {
      "/api/v1/sessions": aPage([
        aSession({
          id: anId(21),
          status: "ended",
          outcome: "done",
          last_activity_at: recent,
          label: aSessionLabel({ issue: "ACME-99", workflow: "/fix", workflows: ["/fix"] }),
        }),
      ]),
    });

    const recentWork = await screen.findByRole("region", { name: "Recent work" });
    const features = within(await within(recentWork).findByRole("list", { name: "Features" }));
    expect(await features.findByText("control-plane")).toBeInTheDocument();
    const tickets = within(await within(recentWork).findByRole("list", { name: "Tickets" }));
    expect(await tickets.findByText("ACME-7")).toBeInTheDocument();
    expect(tickets.getByText("Fix the order export")).toBeInTheDocument();
    expect(tickets.queryByText("ACME-99")).not.toBeInTheDocument();
    expect(calls()).not.toContain("/api/v1/sessions");
  });

  it("leaves the newest 200 sessions the Tickets screen reads to their route", async () => {
    // The Tickets screen read the project's sessions a second before this visit.
    const queryClient = createQueryClient();
    queryClient.setQueryData(sharedSessionsKey, routes["/api/v1/sessions"], {
      updatedAt: Date.now() - 1_000,
    });
    renderFromRead(anOverviewRead(), {}, queryClient);

    // Recent work shows the read's sessions of this week, so the read has answered.
    const recentWork = await screen.findByRole("region", { name: "Recent work" });
    expect(await within(recentWork).findByText("ACME-7")).toBeInTheDocument();
    expect(await within(recentWork).findByText("control-plane")).toBeInTheDocument();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    // The entry still holds the route's whole answer, not the read's narrowed list.
    expect(queryClient.getQueryData(sharedSessionsKey)).toEqual(routes["/api/v1/sessions"]);
  });

  it("reads Recent work from the sessions route once the stream's counts change", async () => {
    // Since the page opened, an agent worked on ACME-99, which the overview read did not have.
    const later = aPage([
      aSession({
        id: anId(21),
        status: "ended",
        outcome: "done",
        last_activity_at: recent,
        label: aSessionLabel({ issue: "ACME-99", workflow: "/fix", workflows: ["/fix"] }),
      }),
    ]);
    const { calls, requests, stream } = renderWithApi(
      <GlobalStreamProvider project={null}>
        <ProjectOverviewScreen />
      </GlobalStreamProvider>,
      {
        routes: { ...routes, [OVERVIEW_READ]: anOverviewRead(), "/api/v1/sessions": later },
        path: "/projects/agent-hub",
        route: "/projects/:project",
        queryClient: createQueryClient(),
      },
    );
    const recentWork = await screen.findByRole("region", { name: "Recent work" });
    expect(await within(recentWork).findByText("ACME-7")).toBeInTheDocument();
    // The first load reads no sessions of its own.
    expect(calls()).not.toContain("/api/v1/sessions");

    // The first counts only arm the refresh; the next ones say something changed.
    const global = stream("/api/v1/events/stream");
    act(() => {
      global.open();
      global.emit("counts", aStreamCounts());
    });
    act(() => {
      global.emit("counts", aStreamCounts({ live_sessions: 4 }));
    });
    // The change reached the screen: what needs you, read with the overview, is read again.
    await waitFor(() => {
      expect(calls()).toContain("/api/v1/needs-you");
    });

    await waitFor(() => {
      expect(
        within(screen.getByRole("region", { name: "Recent work" })).queryByText("ACME-99"),
      ).toBeInTheDocument();
    });
    // Read as the Tickets screen reads them: one shared cache entry.
    const asked = requests
      .map((request) => new URL(request.url))
      .filter((url) => url.pathname === "/api/v1/sessions")
      .map((url) => JSON.stringify(Object.fromEntries([...url.searchParams].sort())));
    expect([...new Set(asked)]).toEqual([
      JSON.stringify({ limit: "200", project: "agent-hub", sort: "-last_activity_at" }),
    ]);
  });

  it("keeps the read's Recent work drawn until the sessions route answers after the counts change", async () => {
    const later = aPage([
      aSession({
        id: anId(21),
        status: "ended",
        outcome: "done",
        last_activity_at: recent,
        label: aSessionLabel({ issue: "ACME-99", workflow: "/fix", workflows: ["/fix"] }),
      }),
    ]);
    const { stream } = renderWithApi(
      <GlobalStreamProvider project={null}>
        <ProjectOverviewScreen />
      </GlobalStreamProvider>,
      {
        routes: { ...routes, [OVERVIEW_READ]: anOverviewRead(), "/api/v1/sessions": later },
        path: "/projects/agent-hub",
        route: "/projects/:project",
        queryClient: createQueryClient(),
      },
    );
    const recentWork = await screen.findByRole("region", { name: "Recent work" });
    expect(await within(recentWork).findByText("ACME-7")).toBeInTheDocument();
    // The sessions route answers only once let through.
    const answer = vi.mocked(globalThis.fetch).getMockImplementation();
    if (answer === undefined) throw new Error("fetch is not stubbed");
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    let asked = 0;
    vi.mocked(globalThis.fetch).mockImplementation(async (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      if (new URL(url, window.location.origin).pathname === "/api/v1/sessions") {
        asked += 1;
        await held;
      }
      return answer(input, init);
    });

    const global = stream("/api/v1/events/stream");
    act(() => {
      global.open();
      global.emit("counts", aStreamCounts());
    });
    act(() => {
      global.emit("counts", aStreamCounts({ live_sessions: 4 }));
    });
    await waitFor(() => {
      expect(asked).toBe(1);
    });
    // Past a skeleton's 300 ms delay, the route still held: the read's sessions stay drawn.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 350));
    });
    const waiting = screen.getByRole("region", { name: "Recent work" });
    expect(within(waiting).queryByText("ACME-7")).toBeInTheDocument();
    expect(waiting.querySelector("[aria-busy='true']")).toBeNull();
    expect(within(waiting).queryByText("ACME-99")).toBeNull();

    release();
    await waitFor(() => {
      expect(
        within(screen.getByRole("region", { name: "Recent work" })).queryByText("ACME-99"),
      ).toBeInTheDocument();
    });
  });

  it("shows the newer session in Recent work after moving in place to another project and back", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      // ACME-99 was worked on after the first visit: the return's read and the route both have it.
      const later = aPage([
        aSession({
          id: anId(21),
          status: "ended",
          outcome: "done",
          last_activity_at: recent,
          label: aSessionLabel({ issue: "ACME-99", workflow: "/fix", workflows: ["/fix"] }),
        }),
        ...weekSessions.items,
      ]);
      let reads = 0;
      const { router } = renderWithApi(<ProjectOverviewScreen />, {
        routes: {
          ...routes,
          [OVERVIEW_READ]: () => {
            reads += 1;
            return anOverviewRead(reads === 1 ? {} : { recent_sessions: later });
          },
          "/api/v1/screens/project-overview/other": anOverviewRead({
            project: aProjectDetail({ name: "other" }),
          }),
          "/api/v1/sessions": later,
        },
        path: "/projects/agent-hub",
        route: "/projects/:project",
        queryClient: createQueryClient(),
      });
      const recentWork = await screen.findByRole("region", { name: "Recent work" });
      expect(await within(recentWork).findByText("ACME-7")).toBeInTheDocument();
      expect(within(recentWork).queryByText("ACME-99")).toBeNull();

      // To another project's overview in place, then Back more than 10 s later.
      await act(async () => {
        await router.navigate("/projects/other");
      });
      expect(router.state.location.pathname).toBe("/projects/other");
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
      });
      vi.setSystemTime(Date.now() + 11_000);
      await act(async () => {
        await router.navigate(-1);
      });
      expect(router.state.location.pathname).toBe("/projects/agent-hub");

      await waitFor(() => {
        expect(
          within(screen.getByRole("region", { name: "Recent work" })).queryByText("ACME-99"),
        ).toBeInTheDocument();
      });
    } finally {
      vi.useRealTimers();
    }
  });

  // A return to the overview draws the last visit's Recent work at once, never a skeleton, while
  // this visit's read is on its way; another project's read never stands in for it.
  it.each([
    { from: "a ticket", away: "/tickets/ACME-7", arrived: "Ticket ACME-7" },
    { from: "another project's overview in place", away: "/projects/other", arrived: "OTHER-5" },
  ])(
    "draws the last visit's Recent work at once on a return from $from, until the read answers",
    async ({ away, arrived }) => {
      vi.useFakeTimers({ toFake: ["Date"] });
      try {
        // ACME-99 was worked on after the first visit: only the return's read has it.
        const later = aPage([
          aSession({
            id: anId(21),
            status: "ended",
            outcome: "done",
            last_activity_at: recent,
            label: aSessionLabel({ issue: "ACME-99", workflow: "/fix", workflows: ["/fix"] }),
          }),
          ...weekSessions.items,
        ]);
        const otherWeek = aPage([
          aSession({
            id: anId(31),
            project: "other",
            status: "ended",
            outcome: "done",
            last_activity_at: recent,
            label: aSessionLabel({ issue: "OTHER-5", workflow: "/fix", workflows: ["/fix"] }),
          }),
        ]);
        let reads = 0;
        const { calls, router } = renderWithApi(
          <Routes>
            <Route path="/projects/:project" element={<ProjectOverviewScreen />} />
            <Route path="/tickets/:id" element={<h1>Ticket ACME-7</h1>} />
          </Routes>,
          {
            routes: {
              ...routes,
              [OVERVIEW_READ]: () => {
                reads += 1;
                return anOverviewRead(reads === 1 ? {} : { recent_sessions: later });
              },
              "/api/v1/screens/project-overview/other": anOverviewRead({
                project: aProjectDetail({ name: "other" }),
                recent_sessions: otherWeek,
              }),
            },
            path: "/projects/agent-hub",
            queryClient: createQueryClient(),
          },
        );
        const first = await screen.findByRole("region", { name: "Recent work" });
        expect(await within(first).findByText("ACME-7")).toBeInTheDocument();
        expect(within(first).queryByText("ACME-99")).toBeNull();
        expect(reads).toBe(1);

        // From here on, agent-hub's overview read answers only once let through.
        const answer = vi.mocked(globalThis.fetch).getMockImplementation();
        if (answer === undefined) throw new Error("fetch is not stubbed");
        let release: () => void = () => undefined;
        const held = new Promise<void>((resolve) => {
          release = resolve;
        });
        let heldReads = 0;
        vi.mocked(globalThis.fetch).mockImplementation(async (input, init) => {
          const url = input instanceof Request ? input.url : String(input);
          if (new URL(url, window.location.origin).pathname === OVERVIEW_READ) {
            heldReads += 1;
            await held;
          }
          return answer(input, init);
        });

        await act(async () => {
          await router.navigate(away);
        });
        expect(await screen.findByText(arrived)).toBeInTheDocument();
        // Back more than 10 s later: every entry the first visit read is stale.
        vi.setSystemTime(Date.now() + 11_000);
        await act(async () => {
          await router.navigate(-1);
        });
        expect(router.state.location.pathname).toBe("/projects/agent-hub");

        // At once: the first visit's rows in both columns, no empty card rows.
        const back = screen.getByRole("region", { name: "Recent work" });
        expect(within(back).queryByText("ACME-7")).toBeInTheDocument();
        expect(within(back).queryByText("control-plane")).toBeInTheDocument();
        expect(back.querySelector("[aria-busy='true']")).toBeNull();
        await waitFor(() => {
          expect(heldReads).toBe(1);
        });

        // Past a skeleton's 300 ms delay, the return's read still held: the same rows, no skeleton.
        await act(async () => {
          await new Promise((resolve) => setTimeout(resolve, 350));
        });
        const waiting = screen.getByRole("region", { name: "Recent work" });
        expect(within(waiting).queryByText("ACME-7")).toBeInTheDocument();
        expect(within(waiting).queryByText("control-plane")).toBeInTheDocument();
        expect(within(waiting).queryByText("OTHER-5")).toBeNull();
        expect(within(waiting).queryByText("ACME-99")).toBeNull();
        expect(waiting.querySelector("[aria-busy='true']")).toBeNull();
        expect(waiting.querySelector(".ah-skel")).toBeNull();
        // The kept answer is read from the cache: no second read, no sessions route.
        expect(heldReads).toBe(1);
        expect(calls()).not.toContain("/api/v1/sessions");

        // This visit's answer then replaces it.
        release();
        await waitFor(() => {
          expect(
            within(screen.getByRole("region", { name: "Recent work" })).queryByText("ACME-99"),
          ).toBeInTheDocument();
        });
        expect(reads).toBe(2);
        expect(heldReads).toBe(1);
        expect(calls()).not.toContain("/api/v1/sessions");
      } finally {
        vi.useRealTimers();
      }
    },
  );

  // The kept read lives as every other cached entry does: while the overview is open, then 5 min
  // from leaving it, however long the stay.
  it("draws the last visit's Recent work at once on a return after a stay past the cache's 5 min, and lets it go 5 min after leaving", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      const clock = aRemovalClock();
      const later = aPage([acme99Session, ...weekSessions.items]);
      let reads = 0;
      const { queryClient, router } = renderWithApi(
        <Routes>
          <Route path="/projects/:project" element={<ProjectOverviewScreen />} />
          <Route path="/tickets/:id" element={<h1>Ticket ACME-7</h1>} />
        </Routes>,
        {
          routes: {
            ...routes,
            [OVERVIEW_READ]: () => {
              reads += 1;
              return anOverviewRead(reads === 1 ? {} : { recent_sessions: later });
            },
          },
          path: "/projects/agent-hub",
          queryClient: createQueryClient(),
        },
      );
      const first = await screen.findByRole("region", { name: "Recent work" });
      expect(await within(first).findByText("ACME-7")).toBeInTheDocument();
      expect(queryClient.getQueryData(keptOverviewKey)).toBeDefined();

      // Six minutes on the overview, then to a ticket and Back 11 s later, the read held.
      act(() => {
        clock.pass(6 * 60_000);
      });
      const read = holdRequests(OVERVIEW_READ);
      await act(async () => {
        await router.navigate("/tickets/ACME-7");
      });
      expect(await screen.findByText("Ticket ACME-7")).toBeInTheDocument();
      clock.pass(11_000);
      await act(async () => {
        await router.navigate(-1);
      });
      expect(router.state.location.pathname).toBe("/projects/agent-hub");

      // At once: the first visit's rows in both columns, no skeleton.
      const back = screen.getByRole("region", { name: "Recent work" });
      expect(within(back).queryByText("ACME-7")).toBeInTheDocument();
      expect(within(back).queryByText("control-plane")).toBeInTheDocument();
      expect(back.querySelector("[aria-busy='true']")).toBeNull();
      await waitFor(() => {
        expect(read.asked()).toBe(1);
      });

      // This visit's answer replaces them, and is the one kept.
      read.release();
      await waitFor(() => {
        expect(
          within(screen.getByRole("region", { name: "Recent work" })).queryByText("ACME-99"),
        ).toBeInTheDocument();
      });

      // Left again: the kept answer stays for 5 min, then the cache lets it go.
      await act(async () => {
        await router.navigate("/tickets/ACME-7");
      });
      expect(await screen.findByText("Ticket ACME-7")).toBeInTheDocument();
      act(() => {
        clock.pass(GC_TIME - 1_000);
      });
      expect(queryClient.getQueryData(keptOverviewKey)).toBeDefined();
      act(() => {
        clock.pass(2_000);
      });
      expect(queryClient.getQueryData(keptOverviewKey)).toBeUndefined();
    } finally {
      vi.useRealTimers();
    }
  });

  // A return whose read gives nothing keeps the last visit's rows drawn until the sessions route
  // has answered, then shows the route's.
  it.each([
    { how: "fails", second: aProblem({ status: 500, title: "Internal error" }) },
    { how: "does not answer in time", second: "pending" },
  ])(
    "keeps the last visit's Recent work drawn on a return whose read $how, until the sessions route answers",
    async ({ second }) => {
      vi.useFakeTimers({ toFake: ["Date"] });
      try {
        let reads = 0;
        const { router } = renderWithApi(
          <Routes>
            <Route path="/projects/:project" element={<ProjectOverviewScreen />} />
            <Route path="/tickets/:id" element={<h1>Ticket ACME-7</h1>} />
          </Routes>,
          {
            routes: {
              ...routes,
              [OVERVIEW_READ]: () => {
                reads += 1;
                return reads === 1 ? anOverviewRead() : second;
              },
              "/api/v1/sessions": aPage([acme99Session]),
            },
            path: "/projects/agent-hub",
            queryClient: createQueryClient(),
          },
        );
        const first = await screen.findByRole("region", { name: "Recent work" });
        expect(await within(first).findByText("ACME-7")).toBeInTheDocument();

        const sessions = holdRequests("/api/v1/sessions");
        await act(async () => {
          await router.navigate("/tickets/ACME-7");
        });
        expect(await screen.findByText("Ticket ACME-7")).toBeInTheDocument();
        vi.setSystemTime(Date.now() + 11_000);
        await act(async () => {
          await router.navigate(-1);
        });
        expect(router.state.location.pathname).toBe("/projects/agent-hub");

        // The return's read gave nothing, so Recent work asks its route, which is held.
        await waitFor(
          () => {
            expect(sessions.asked()).toBe(1);
          },
          { timeout: SCREEN_READ_TIMEOUT_MS + 2_000 },
        );
        expect(reads).toBe(2);
        // Past a skeleton's 300 ms delay: the last visit's rows in both columns, no skeleton.
        await act(async () => {
          await new Promise((resolve) => setTimeout(resolve, 350));
        });
        const waiting = screen.getByRole("region", { name: "Recent work" });
        expect(within(waiting).queryByText("ACME-7")).toBeInTheDocument();
        expect(within(waiting).queryByText("control-plane")).toBeInTheDocument();
        expect(waiting.querySelector("[aria-busy='true']")).toBeNull();
        expect(waiting.querySelector(".ah-skel")).toBeNull();

        // Once the route answers, its rows replace them.
        sessions.release();
        await waitFor(() => {
          expect(
            within(screen.getByRole("region", { name: "Recent work" })).queryByText("ACME-99"),
          ).toBeInTheDocument();
        });
        expect(
          within(screen.getByRole("region", { name: "Recent work" })).queryByText("ACME-7"),
        ).toBeNull();
      } finally {
        vi.useRealTimers();
      }
    },
    15_000,
  );

  // A return draws the newer of the two answers the cache holds: the last overview read, or the
  // sessions route's, which Recent work moved to once the stream's counts changed.
  it("draws the sessions route's newer Recent work at once on a return after the counts moved it there", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      const later = aPage([acme99Session, ...weekSessions.items]);
      let reads = 0;
      const { queryClient, router, stream } = renderWithApi(
        <GlobalStreamProvider project={null}>
          <Routes>
            <Route path="/projects/:project" element={<ProjectOverviewScreen />} />
            <Route path="/tickets/:id" element={<h1>Ticket ACME-99</h1>} />
          </Routes>
        </GlobalStreamProvider>,
        {
          routes: {
            ...routes,
            [OVERVIEW_READ]: () => {
              reads += 1;
              return anOverviewRead(reads === 1 ? {} : { recent_sessions: later });
            },
            "/api/v1/sessions": later,
          },
          path: "/projects/agent-hub",
          queryClient: createQueryClient(),
        },
      );
      const first = await screen.findByRole("region", { name: "Recent work" });
      expect(await within(first).findByText("ACME-7")).toBeInTheDocument();
      expect(within(first).queryByText("ACME-99")).toBeNull();

      // A second later the stream's counts change: Recent work reads the sessions route.
      vi.setSystemTime(Date.now() + 1_000);
      const global = stream("/api/v1/events/stream");
      act(() => {
        global.open();
        global.emit("counts", aStreamCounts());
      });
      act(() => {
        global.emit("counts", aStreamCounts({ live_sessions: 4 }));
      });
      await waitFor(() => {
        expect(
          within(screen.getByRole("region", { name: "Recent work" })).queryByText("ACME-99"),
        ).toBeInTheDocument();
      });
      expect(queryClient.getQueryState(sharedSessionsKey)?.dataUpdatedAt).toBeGreaterThan(
        queryClient.getQueryState(keptOverviewKey)?.dataUpdatedAt ?? Infinity,
      );

      // ACME-99 is opened, then Back 11 s later, the overview read held.
      const read = holdRequests(OVERVIEW_READ);
      const sessions = holdRequests("/api/v1/sessions");
      await act(async () => {
        await router.navigate("/tickets/ACME-99");
      });
      expect(await screen.findByText("Ticket ACME-99")).toBeInTheDocument();
      vi.setSystemTime(Date.now() + 11_000);
      await act(async () => {
        await router.navigate(-1);
      });
      expect(router.state.location.pathname).toBe("/projects/agent-hub");

      // At once, and past a skeleton's 300 ms delay: the route's rows, ACME-99 among them.
      const back = screen.getByRole("region", { name: "Recent work" });
      expect(within(back).queryByText("ACME-99")).toBeInTheDocument();
      expect(back.querySelector("[aria-busy='true']")).toBeNull();
      await waitFor(() => {
        expect(read.asked()).toBe(1);
      });
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 350));
      });
      const waiting = screen.getByRole("region", { name: "Recent work" });
      expect(within(waiting).queryByText("ACME-99")).toBeInTheDocument();
      expect(within(waiting).queryByText("ACME-7")).toBeInTheDocument();
      expect(waiting.querySelector("[aria-busy='true']")).toBeNull();
      // Both answers come from the cache: no sessions request.
      expect(sessions.asked()).toBe(0);

      // This visit's read then answers, and Recent work stays on it.
      read.release();
      await waitFor(() => {
        expect(reads).toBe(2);
      });
      expect(
        within(screen.getByRole("region", { name: "Recent work" })).queryByText("ACME-99"),
      ).toBeInTheDocument();
      expect(sessions.asked()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  // Once the sessions route has failed after a return whose read failed, Recent work shows the
  // route's problem; the last visit's rows never stand in for it.
  it("shows Recent work's problem with Try again on a return whose read and sessions route both fail", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      let reads = 0;
      const { queryClient, router } = renderWithApi(
        <Routes>
          <Route path="/projects/:project" element={<ProjectOverviewScreen />} />
          <Route path="/tickets/:id" element={<h1>Ticket ACME-7</h1>} />
        </Routes>,
        {
          routes: {
            ...routes,
            [OVERVIEW_READ]: () => {
              reads += 1;
              return reads === 1
                ? anOverviewRead()
                : aProblem({ status: 500, title: "Internal error" });
            },
            "/api/v1/sessions": aProblem({ status: 500, title: "Internal error" }),
          },
          path: "/projects/agent-hub",
          queryClient: createQueryClient(),
        },
      );
      const first = await screen.findByRole("region", { name: "Recent work" });
      expect(await within(first).findByText("ACME-7")).toBeInTheDocument();

      await act(async () => {
        await router.navigate("/tickets/ACME-7");
      });
      expect(await screen.findByText("Ticket ACME-7")).toBeInTheDocument();
      vi.setSystemTime(Date.now() + 11_000);
      await act(async () => {
        await router.navigate(-1);
      });
      expect(router.state.location.pathname).toBe("/projects/agent-hub");

      // The return's read failed, then the sessions route: the route's problem, with Try again.
      expect(await screen.findByText("Could not load tickets")).toBeInTheDocument();
      const back = screen.getByRole("region", { name: "Recent work" });
      const tickets = within(back).getByRole("heading", { name: "Tickets" }).parentElement
        ?.parentElement;
      if (!tickets) throw new Error("no Tickets column");
      expect(within(tickets).getByText("Could not load tickets")).toBeInTheDocument();
      expect(within(tickets).getByRole("button", { name: "Try again" })).toBeInTheDocument();
      expect(reads).toBe(2);
      // The last visit's answer is still in the cache, yet none of its rows are drawn.
      expect(queryClient.getQueryData(keptOverviewKey)).toBeDefined();
      expect(within(back).queryByText("ACME-7")).toBeNull();
      expect(within(back).queryByText("control-plane")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  // A return whose read gives nothing draws the newer of the two answers the cache holds: here the
  // sessions route's, read by the Tickets screen after the last overview read.
  it.each([
    { how: "fails", second: aProblem({ status: 500, title: "Internal error" }) },
    { how: "does not answer in time", second: "pending" },
  ])(
    "draws the sessions route's newer cached Recent work on a return whose read $how, while the route is asked",
    async ({ second }) => {
      vi.useFakeTimers({ toFake: ["Date"] });
      try {
        let reads = 0;
        const { queryClient, router } = renderWithApi(
          <Routes>
            <Route path="/projects/:project" element={<ProjectOverviewScreen />} />
            <Route path="/tickets" element={<h1>Tickets screen</h1>} />
          </Routes>,
          {
            routes: {
              ...routes,
              [OVERVIEW_READ]: () => {
                reads += 1;
                return reads === 1 ? anOverviewRead() : second;
              },
              "/api/v1/sessions": aPage([acme99Session]),
            },
            path: "/projects/agent-hub",
            queryClient: createQueryClient(),
          },
        );
        const first = await screen.findByRole("region", { name: "Recent work" });
        expect(await within(first).findByText("ACME-7")).toBeInTheDocument();
        expect(within(first).queryByText("ACME-99")).toBeNull();

        // To the Tickets screen, which reads the project's newest 200 sessions 5 s later.
        await act(async () => {
          await router.navigate("/tickets");
        });
        expect(await screen.findByText("Tickets screen")).toBeInTheDocument();
        vi.setSystemTime(Date.now() + 5_000);
        queryClient.setQueryData(sharedSessionsKey, aPage([acme99Session]));
        expect(queryClient.getQueryState(sharedSessionsKey)?.dataUpdatedAt).toBeGreaterThan(
          queryClient.getQueryState(keptOverviewKey)?.dataUpdatedAt ?? Infinity,
        );

        // Back 11 s later: the read gives nothing, so Recent work asks its route, which is held.
        const sessions = holdRequests("/api/v1/sessions");
        vi.setSystemTime(Date.now() + 11_000);
        await act(async () => {
          await router.navigate(-1);
        });
        expect(router.state.location.pathname).toBe("/projects/agent-hub");
        await waitFor(
          () => {
            expect(sessions.asked()).toBe(1);
          },
          { timeout: SCREEN_READ_TIMEOUT_MS + 2_000 },
        );
        expect(reads).toBe(2);

        // Past a skeleton's 300 ms delay: the route's cached rows, not the older overview read's.
        await act(async () => {
          await new Promise((resolve) => setTimeout(resolve, 350));
        });
        const waiting = screen.getByRole("region", { name: "Recent work" });
        expect(within(waiting).queryByText("ACME-99")).toBeInTheDocument();
        expect(within(waiting).queryByText("ACME-7")).toBeNull();
        expect(waiting.querySelector("[aria-busy='true']")).toBeNull();
      } finally {
        vi.useRealTimers();
      }
    },
    15_000,
  );

  // A first visit keeps nothing of its own, but the Tickets screen's answer may be in the cache.
  it("draws the sessions route's cached Recent work on a first visit while its read is on its way", async () => {
    // 11 s before, the Tickets screen read the project's newest 200 sessions: past the client's
    // 10 s staleTime, so the route would ask again if it were on. A second before, another screen
    // read the project.
    const queryClient = createQueryClient();
    queryClient.setQueryData(sharedSessionsKey, aPage([acme99Session]), {
      updatedAt: Date.now() - 11_000,
    });
    queryClient.setQueryData(
      apiKey("/api/v1/projects/{project}", { path: { project: "agent-hub" } }),
      routes["/api/v1/projects/agent-hub"],
      { updatedAt: Date.now() - 1_000 },
    );
    const { router } = renderWithApi(
      <Routes>
        <Route path="/projects/:project" element={<ProjectOverviewScreen />} />
        <Route path="/tickets" element={<h1>Tickets screen</h1>} />
      </Routes>,
      {
        routes: { ...routes, [OVERVIEW_READ]: anOverviewRead() },
        path: "/tickets",
        queryClient,
      },
    );
    expect(await screen.findByText("Tickets screen")).toBeInTheDocument();
    expect(queryClient.getQueryData(keptOverviewKey)).toBeUndefined();

    // To the overview, its read held.
    const read = holdRequests(OVERVIEW_READ);
    const sessions = holdRequests("/api/v1/sessions");
    await act(async () => {
      await router.navigate("/projects/agent-hub");
    });
    await waitFor(() => {
      expect(read.asked()).toBe(1);
    });

    // Past a skeleton's 300 ms delay: the route's cached rows in the Tickets column, no skeleton.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 350));
    });
    const waiting = screen.getByRole("region", { name: "Recent work" });
    const tickets = within(waiting).getByRole("heading", { name: "Tickets" }).parentElement
      ?.parentElement;
    if (!tickets) throw new Error("no Tickets column");
    expect(within(tickets).getByRole("list", { name: "Tickets" })).toHaveTextContent("ACME-99");
    expect(tickets.querySelector("[aria-busy='true']")).toBeNull();
    // Read from the cache: the route is not asked while the read is on its way.
    expect(sessions.asked()).toBe(0);

    // This visit's read then answers, and Recent work draws its sessions.
    read.release();
    await waitFor(() => {
      expect(
        within(screen.getByRole("region", { name: "Recent work" })).queryByText("ACME-7"),
      ).toBeInTheDocument();
    });
    expect(
      within(screen.getByRole("region", { name: "Recent work" })).queryByText("ACME-99"),
    ).toBeNull();
    expect(sessions.asked()).toBe(0);
  });

  // When the last overview read and the sessions route's cached answer were written at the same
  // moment, a return draws the overview read's.
  it("draws the last visit's Recent work on a return when the sessions route's cached answer is as old", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      const { queryClient, router } = renderWithApi(
        <Routes>
          <Route path="/projects/:project" element={<ProjectOverviewScreen />} />
          <Route path="/tickets" element={<h1>Tickets screen</h1>} />
        </Routes>,
        {
          routes: {
            ...routes,
            [OVERVIEW_READ]: anOverviewRead(),
            "/api/v1/sessions": aPage([acme99Session]),
          },
          path: "/projects/agent-hub",
          queryClient: createQueryClient(),
        },
      );
      const first = await screen.findByRole("region", { name: "Recent work" });
      expect(await within(first).findByText("ACME-7")).toBeInTheDocument();

      // To the Tickets screen, whose answer is stamped with the overview read's own time.
      await act(async () => {
        await router.navigate("/tickets");
      });
      expect(await screen.findByText("Tickets screen")).toBeInTheDocument();
      const keptAt = queryClient.getQueryState(keptOverviewKey)?.dataUpdatedAt ?? 0;
      expect(keptAt).toBeGreaterThan(0);
      queryClient.setQueryData(sharedSessionsKey, aPage([acme99Session]), { updatedAt: keptAt });
      expect(queryClient.getQueryState(sharedSessionsKey)?.dataUpdatedAt).toBe(keptAt);

      // Back 11 s later, the read held.
      const read = holdRequests(OVERVIEW_READ);
      const sessions = holdRequests("/api/v1/sessions");
      vi.setSystemTime(Date.now() + 11_000);
      await act(async () => {
        await router.navigate(-1);
      });
      expect(router.state.location.pathname).toBe("/projects/agent-hub");
      await waitFor(() => {
        expect(read.asked()).toBe(1);
      });

      // The tie goes to the last visit's read: its rows, not the route's.
      const back = screen.getByRole("region", { name: "Recent work" });
      expect(within(back).queryByText("ACME-7")).toBeInTheDocument();
      expect(within(back).queryByText("ACME-99")).toBeNull();
      expect(back.querySelector("[aria-busy='true']")).toBeNull();
      expect(sessions.asked()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  // The sessions route answers the opposite each time, so a screen that read it would show the
  // other state.
  it.each([
    {
      has_sessions: false,
      sessions: weekSessions,
      shown: "No sessions yet.",
      absent: "No feature was worked on in the last 7 days.",
    },
    {
      has_sessions: true,
      sessions: aPage([]),
      shown: "No feature was worked on in the last 7 days.",
      absent: "No sessions yet.",
    },
  ])(
    "says there are no sessions yet when the overview read has none (has_sessions $has_sessions)",
    async ({ has_sessions, sessions, shown, absent }) => {
      const { calls } = renderFromRead(
        anOverviewRead({ recent_sessions: aPage([]), has_sessions }),
        { "/api/v1/sessions": sessions },
      );

      const recentWork = await screen.findByRole("region", { name: "Recent work" });
      expect(await within(recentWork).findByText(shown)).toBeInTheDocument();
      expect(within(recentWork).queryByText(absent)).not.toBeInTheDocument();
      expect(calls()).not.toContain("/api/v1/sessions");
    },
  );

  // While the read is on its way, the empty states follow the cached answer drawn. The last
  // visit's read says whether the project has any session at all.
  it("shows the last visit's empty week, not No sessions yet, on a return whose read is on its way", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      const { queryClient, router } = renderWithApi(
        <Routes>
          <Route path="/projects/:project" element={<ProjectOverviewScreen />} />
          <Route path="/tickets" element={<h1>Tickets screen</h1>} />
        </Routes>,
        {
          routes: {
            ...routes,
            [OVERVIEW_READ]: anOverviewRead({ recent_sessions: aPage([]), has_sessions: true }),
          },
          path: "/projects/agent-hub",
          queryClient: createQueryClient(),
        },
      );
      const first = await screen.findByRole("region", { name: "Recent work" });
      expect(
        await within(first).findByText("No ticket was worked on in the last 7 days."),
      ).toBeInTheDocument();
      expect(queryClient.getQueryData(keptOverviewKey)).toBeDefined();
      expect(queryClient.getQueryData(sharedSessionsKey)).toBeUndefined();

      // To the Tickets screen, then Back 11 s later, the read held.
      const read = holdRequests(OVERVIEW_READ);
      await act(async () => {
        await router.navigate("/tickets");
      });
      expect(await screen.findByText("Tickets screen")).toBeInTheDocument();
      vi.setSystemTime(Date.now() + 11_000);
      await act(async () => {
        await router.navigate(-1);
      });
      expect(router.state.location.pathname).toBe("/projects/agent-hub");
      await waitFor(() => {
        expect(read.asked()).toBe(1);
      });

      // The project has sessions, none this week: the empty-week lines.
      const back = screen.getByRole("region", { name: "Recent work" });
      expect(
        within(back).queryByText("No ticket was worked on in the last 7 days."),
      ).toBeInTheDocument();
      expect(within(back).queryByText("No sessions yet.")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  // The sessions route's cached answer says it by being empty.
  it("says there are no sessions yet on a first visit whose read is on its way, from the sessions route's empty cached answer", async () => {
    // A second before, the Tickets screen read the project's newest 200 sessions, none, and
    // another screen the project.
    const queryClient = createQueryClient();
    queryClient.setQueryData(sharedSessionsKey, aPage([]), { updatedAt: Date.now() - 1_000 });
    queryClient.setQueryData(
      apiKey("/api/v1/projects/{project}", { path: { project: "agent-hub" } }),
      routes["/api/v1/projects/agent-hub"],
      { updatedAt: Date.now() - 1_000 },
    );
    const { router } = renderWithApi(
      <Routes>
        <Route path="/projects/:project" element={<ProjectOverviewScreen />} />
        <Route path="/tickets" element={<h1>Tickets screen</h1>} />
      </Routes>,
      {
        routes: {
          ...routes,
          [OVERVIEW_READ]: anOverviewRead({ recent_sessions: aPage([]), has_sessions: false }),
        },
        path: "/tickets",
        queryClient,
      },
    );
    expect(await screen.findByText("Tickets screen")).toBeInTheDocument();
    expect(queryClient.getQueryData(keptOverviewKey)).toBeUndefined();

    // To the overview, its read held.
    const read = holdRequests(OVERVIEW_READ);
    await act(async () => {
      await router.navigate("/projects/agent-hub");
    });
    await waitFor(() => {
      expect(read.asked()).toBe(1);
    });

    // No session at all: "No sessions yet.", not the empty-week lines.
    const waiting = await screen.findByRole("region", { name: "Recent work" });
    expect(within(waiting).queryByText("No sessions yet.")).toBeInTheDocument();
    expect(within(waiting).queryByText("No ticket was worked on in the last 7 days.")).toBeNull();
  });
});
