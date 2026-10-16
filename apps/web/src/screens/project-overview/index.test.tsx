import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
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

const routes: ApiRoutes = {
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
  "/api/v1/sessions": aPage([
    aSession({
      id: anId(1),
      status: "ended",
      outcome: "error",
      errors: 6,
      started_at: at(-9000),
      ended_at: at(-6000),
      agent: "main",
      label: aSessionLabel({ issue: "TIP-1511", repo: "tipple", branch: "main" }),
    }),
    aSession({
      id: anId(2),
      status: "live",
      label: aSessionLabel({ issue: null, workflow: "/create-plan", branch: "dev/agh-9-x" }),
      started_at: at(-100),
    }),
  ]),
  "/api/v1/needs-you": aPage([
    aNeedsYouItem({
      verb: "Approve the plan",
      context: "agent-hub · AGH-131 · Doctor JSON output",
      href: `/approvals/${anId(3)}`,
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
      `/approvals/${anId(3)}`,
    );
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

  it("lists recent sessions live first and opens one on click", async () => {
    const user = userEvent.setup();
    const { router } = renderProject();

    const table = await screen.findByRole("table", { name: "Recent sessions" });
    await within(table).findByText("TIP-1511 · /feature");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("/create-plan");
    expect(rows[1]).toHaveTextContent("Error");
    await user.click(within(table).getByText("TIP-1511 · /feature"));
    expect(router.state.location.pathname).toBe(`/sessions/${anId(1)}`);
  });

  it("names each recent session by its label, never by its agent (label, AC-201.4)", async () => {
    renderProject();

    const table = await screen.findByRole("table", { name: "Recent sessions" });
    await within(table).findByText("TIP-1511 · /feature");
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(headers).not.toContain("Agent");
    expect(headers).toEqual(["What", "Status", "Started", "Took", "Cost"]);
    expect(within(table).getByText("tipple · main")).toBeInTheDocument();
    expect(within(table).getByText("agent-hub · dev/agh-9-x")).toBeInTheDocument();
    const mains = within(table).queryAllByText(/\bmain\b/);
    expect(mains.map((node) => node.textContent)).toEqual(["tipple · main"]);
  });

  it("folds setup and health away for engineers, with findings, repos and the hub", async () => {
    const user = userEvent.setup();
    renderProject();

    const setup = (await screen.findByText("Setup and health")).closest("details");
    expect(setup).not.toHaveAttribute("open");
    expect(await within(setup as HTMLElement).findByText("2 things to fix")).toBeInTheDocument();
    await user.click(screen.getByText("Setup and health"));
    expect(setup).toHaveAttribute("open");

    const scope = within(setup as HTMLElement);
    expect(await scope.findByText("1 error · 1 warning · 0 info")).toBeInTheDocument();
    const rules = scope.getAllByText(/instructions\.size|brain\.memory/).map((n) => n.textContent);
    expect(rules).toEqual(["instructions.size", "brain.memory"]);

    const table = scope.getByRole("table", { name: "Repos" });
    expect(within(table).getAllByText("make check-fast")).toHaveLength(3);
    expect(within(table).getByText("Missing")).toBeInTheDocument();
    expect(within(table).getByText("132 lines")).toBeInTheDocument();

    expect(scope.getByText("Sync pending (lock 0.3.0, pin 0.4.0)")).toBeInTheDocument();
    expect(scope.getByText("bench")).toBeInTheDocument();
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
      expect(await screen.findByRole("table", { name: "Recent sessions" })).toBeInTheDocument();
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

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = renderProject();

    await screen.findByText("Cap the tracker team list");
    await screen.findByText("/create-plan");
    expect(await seriousViolations(container)).toEqual([]);
  });
});
