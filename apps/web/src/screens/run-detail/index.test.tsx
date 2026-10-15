import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  anApproval,
  anEngineRun,
  anId,
  aPage,
  aProblem,
  aRun,
  at,
  aWorkflowDetail,
  renderWithApi,
  type ApiRoutes,
  type WorkflowRun,
} from "../../testing/builders";
import { RunDetailScreen } from ".";

const S1 = anId(1, "7c2e41a0");
const S2 = anId(2, "9b0d1f37");
const FAILING_EVENT = anId(40, "0192aaaa");

type Step = WorkflowRun["steps"][number];
function step(
  key: Step["key"],
  attempt: number,
  from: number,
  to: number | null,
  status: Step["status"],
  sessions: string[] = [],
  max = 2,
): Step {
  return {
    key,
    attempt,
    max_attempts: max,
    started_at: at(from),
    ended_at: to === null ? null : at(to),
    status,
    reason: status === "failed" ? "make check exit 2" : null,
    session_ids: sessions,
  };
}

const failedRun = aRun({
  id: "01923e08-11aa-7b3c-8f00-6a7b8c9d0e1f",
  issue: { key: "AGH-79", title: "Guard bypass", url: null },
  stage: "FAILED",
  started_at: at(0),
  ended_at: at(4320),
  cost_usd: "6.8040",
  caps: {
    budget_usd: "10.0000",
    max_turns: 120,
    model: "claude-model-a",
    tracker_transport: "linear-graphql",
  },
  session_ids: [S1, S2],
  failure: {
    stage: "VERIFYING",
    reason: "make check exited 2: 3 failing tests in test_guard.py",
    failing_event_id: FAILING_EVENT,
  },
  gate_results: [
    {
      event_id: anId(30, "0192aaaa"),
      command: "make check",
      exit_code: 2,
      duration_ms: 184000,
      result: "failed",
    },
    {
      event_id: anId(31, "0192aaaa"),
      command: "make check",
      exit_code: 2,
      duration_ms: 178000,
      result: "failed",
    },
  ],
  steps: [
    step("pick", 1, 0, 2, "ok", [], 1),
    step("worktree", 1, 2, 16, "ok", [], 1),
    step("implement", 1, 20, 1460, "ok", [S1]),
    step("verify", 1, 2280, 2464, "failed"),
    step("implement", 2, 2520, 3540, "ok", [S2]),
    step("verify", 2, 3960, 4138, "failed"),
  ],
});

/** The element at `index`, failing the test when it is missing. */
function nth(elements: HTMLElement[], index: number): HTMLElement {
  const element = elements[index];
  if (!element) throw new Error(`No element at ${String(index)}`);
  return element;
}
function renderRun(
  run: WorkflowRun | ReturnType<typeof aProblem> | "pending",
  id = failedRun.id,
  query = "",
) {
  return renderWithApi(<RunDetailScreen />, {
    routes: { [`/api/v1/workflow-runs/${id}`]: run },
    path: `/runs/${id}${query}`,
    route: "/runs/:runId",
  });
}

describe("RunDetailScreen", () => {
  it("states stage, attempt and reason in the failure banner and links the failing moment", async () => {
    renderRun(failedRun);

    const banner = await screen.findByRole("region", { name: "Failure" });
    expect(within(banner).getByText("Failed at Verifying · attempt 2 of 2")).toBeInTheDocument();
    expect(
      within(banner).getByText("make check exited 2: 3 failing tests in test_guard.py"),
    ).toBeInTheDocument();
    expect(within(banner).getByRole("link", { name: /Open failing moment/ })).toHaveAttribute(
      "href",
      `/sessions/${S2}?tab=timeline&event=${FAILING_EVENT}`,
    );
  });

  it("shows the loop with attempt 2 of 2 in the pipeline", async () => {
    renderRun(failedRun);

    const pipe = await screen.findByRole("list", { name: "Run stages" });
    const verifying = nth(within(pipe).getAllByRole("listitem"), 3);
    expect(verifying).toHaveAttribute("data-state", "failed");
    expect(within(verifying).getByText(/attempt 2 of 2/)).toBeInTheDocument();
    expect(within(nth(within(pipe).getAllByRole("listitem"), 0)).queryByText(/attempt/)).toBeNull();
    expect(
      screen.getByText("on fail: back to Implementing · attempt 2 of 2 · cap reached"),
    ).toBeInTheDocument();
    expect(within(pipe).getAllByRole("listitem")[4]).toHaveAttribute("data-state", "pending");
  });

  it("disables Retry from verify with the P4 tag", async () => {
    renderRun(failedRun);

    const retry = await screen.findByRole("button", { name: /Retry from verify/ });
    expect(retry).toBeDisabled();
    expect(within(retry).getByText("P4")).toHaveClass("ah-phase");
    expect(retry).toHaveAttribute("title", "Available in Phase 4. This version is read-only.");
  });

  it("draws one Gantt lane per step attempt with session links", async () => {
    renderRun(failedRun);

    const gantt = await screen.findByRole("list", { name: "Steps over time" });
    const lanes = within(gantt).getAllByRole("listitem");
    expect(lanes.map((lane) => lane.textContent.split(/\d/)[0])).toEqual([
      "Picked #",
      "Worktree #",
      "Implement #",
      "Verify #",
      "Implement #",
      "Verify #",
    ]);
    expect(within(nth(lanes, 2)).getByRole("link", { name: "7c2e41a0" })).toHaveAttribute(
      "href",
      `/sessions/${S1}`,
    );
  });

  it("names an engine node's lane by its id when the step has no label", async () => {
    renderRun(
      aRun({
        workflow: "ship",
        steps: [step("build", 1, 0, 30, "ok"), step("review__lint", 1, 30, 30, "skipped")],
      }),
    );

    const gantt = await screen.findByRole("list", { name: "Steps over time" });
    const lanes = within(gantt).getAllByRole("listitem");
    expect(lanes.map((lane) => lane.textContent.split(/\d/)[0])).toEqual([
      "build #",
      "review__lint #",
    ]);
  });

  it("opens the gate log, caps, tracker and PR tabs", async () => {
    const user = userEvent.setup();
    const { router } = renderRun(failedRun);

    const banner = await screen.findByRole("region", { name: "Failure" });
    await user.click(within(banner).getByRole("button", { name: "View gate log" }));
    expect(router.state.location.search).toBe("?tab=gates");
    const gates = await screen.findByRole("table", { name: "Gate results" });
    expect(within(gates).getAllByText("make check")).toHaveLength(2);
    expect(
      within(gates).getAllByText("3 min 4 s").length +
        within(gates).getAllByText("2 min 58 s").length,
    ).toBe(2);

    await user.click(screen.getByRole("tab", { name: "Caps" }));
    const caps = screen.getByRole("table", { name: "Caps" });
    expect(within(caps).getByText("$6.8040 / $10.0000")).toBeInTheDocument();
    expect(within(caps).getByText("100 % · cap reached")).toBeInTheDocument();
    expect(
      screen.getByText(/2 sessions · total \$6\.8040 · estimated from transcripts/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Tracker writes" }));
    expect(screen.getByText(/Linear is not connected in this version\./)).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "PR and CI" }));
    expect(screen.getByText("No PR.")).toBeInTheDocument();
  });

  it("offers the gate log when no failing event is known", async () => {
    const user = userEvent.setup();
    renderRun(
      aRun({
        ...failedRun,
        failure: { stage: "IMPLEMENTING", reason: null, failing_event_id: null },
        gate_results: [],
        steps: [step("implement", 1, 0, 50, "failed", [], 1)],
      }),
    );

    const banner = await screen.findByRole("region", { name: "Failure" });
    expect(within(banner).getByText("Failed at Implementing · attempt 1 of 1")).toBeInTheDocument();
    expect(
      within(banner).getByText("No reason was recorded. See the gate log."),
    ).toBeInTheDocument();
    await user.click(within(banner).getByRole("button", { name: "Open gate log" }));
    expect(await screen.findByText("No gate has run yet.")).toBeInTheDocument();
  });

  it("names the failed gate when the run has no reason", async () => {
    renderRun(
      aRun({ ...failedRun, failure: { stage: "VERIFYING", reason: null, failing_event_id: null } }),
    );

    expect(await screen.findByText("make check exited 2")).toBeInTheDocument();
  });

  it("refetches a running run when its stream reports a change", async () => {
    const running = aRun({
      id: "live-run",
      stage: "IMPLEMENTING",
      ended_at: null,
      started_at: at(0),
      steps: [step("pick", 1, 0, 2, "ok", [], 1), step("implement", 1, 5, null, "running", [S1])],
    });
    const { requests, stream } = renderRun(running, "live-run");

    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByText(/· running$/)).toBeInTheDocument();
    const runStream = stream("/api/v1/workflow-runs/live-run/stream");
    act(() => {
      runStream.open();
      runStream.emit("step", { key: "implement" });
    });
    await waitFor(() => {
      expect(requests.filter((r) => r.url.endsWith("/workflow-runs/live-run")).length).toBe(2);
    });
    expect(screen.queryByRole("region", { name: "Failure" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Retry/ })).not.toBeInTheDocument();
  });

  it("shows the reported line, the dry-run banner and the PR link of a finished dry run", async () => {
    const user = userEvent.setup();
    renderRun(
      aRun({
        id: "done-run",
        stage: "REPORTED",
        mode: "dry_run",
        ended_at: at(3600),
        pr_url: "https://example.invalid/pr/69",
        caps: null,
        steps: [],
      }),
      "done-run",
      "?tab=pr",
    );

    expect(await screen.findByText(/^Reported at .* · PR opened$/)).toBeInTheDocument();
    expect(screen.getByText(/Dry run: no commands executed/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the pull request/ })).toHaveAttribute(
      "href",
      "https://example.invalid/pr/69",
    );
    await user.click(screen.getByRole("tab", { name: /Sessions/ }));
    expect(screen.getByText("No sessions in this run yet")).toBeInTheDocument();
  });

  describe("engine run graph", () => {
    const engine = anEngineRun();
    const WORKFLOW = "/api/v1/workflows/agent-hub/feature-flow";

    function renderEngine(workflow: ApiRoutes[string] = aWorkflowDetail(), query = "") {
      return renderWithApi(<RunDetailScreen />, {
        routes: { [`/api/v1/workflow-runs/${engine.id}`]: engine, [WORKFLOW]: workflow },
        path: `/runs/${engine.id}${query}`,
        route: "/runs/:runId",
      });
    }

    function nodeButton(graph: HTMLElement, id: string): HTMLElement {
      const found = within(graph)
        .getAllByRole("button")
        .find((button) => button.getAttribute("data-node-id") === id);
      if (!found) throw new Error(`No node ${id}`);
      return found;
    }

    it("draws the declared nodes with state, attempts, skip cause and failure kind", async () => {
      renderEngine();

      const graph = await screen.findByRole("group", { name: "Run graph" });
      expect(within(graph).getAllByRole("list")).toHaveLength(3);
      expect(nodeButton(graph, "plan")).toHaveTextContent("Completed");
      expect(nodeButton(graph, "build")).toHaveAttribute("data-state", "failed");
      expect(nodeButton(graph, "build")).toHaveTextContent("Failed · attempt 2 · Timeout");
      expect(nodeButton(graph, "docs")).toHaveTextContent("Skipped · condition false");
      expect(nodeButton(graph, "review")).toHaveTextContent("Skipped · upstream failed");
      expect(screen.queryByRole("list", { name: "Run stages" })).toBeNull();
    });

    it("names the failing node and its kind in the failure banner", async () => {
      renderEngine();

      const banner = await screen.findByRole("region", { name: "Failure" });
      expect(within(banner).getByText("Failed at build · attempt 2 · Timeout")).toBeInTheDocument();
    });

    it("opens a node's panel with its reason, attempts and sessions", async () => {
      const user = userEvent.setup();
      renderEngine();

      const graph = await screen.findByRole("group", { name: "Run graph" });
      await user.click(nodeButton(graph, "plan"));

      const panel = await screen.findByRole("complementary", { name: "Node plan" });
      expect(panel).toHaveTextContent("attempt 1 of 2");
      expect(panel).toHaveTextContent("Not in run events");
      expect(within(panel).getByRole("link", { name: /5091b986/ })).toHaveAttribute(
        "href",
        `/sessions/${anId(7, "5091b986")}`,
      );

      await user.click(nodeButton(graph, "build"));
      const build = await screen.findByRole("complementary", { name: "Node build" });
      expect(build).toHaveTextContent("Timeout");
      expect(build).toHaveTextContent("timeout");
    });

    it("says when the graph shows another revision than the run's", async () => {
      renderEngine(aWorkflowDetail({ revision: 4 }));

      expect(
        await screen.findByText(/This run used r3; the graph shows the current r4/),
      ).toBeInTheDocument();
    });

    it("falls back to the run's steps when the workflow cannot be read", async () => {
      renderEngine(aProblem({ status: 404, title: "Not found" }));

      const graph = await screen.findByRole("group", { name: "Run graph" });
      expect(screen.getByText(/The workflow feature-flow could not be read/)).toBeInTheDocument();
      expect(
        within(graph)
          .getAllByRole("button")
          .map((b) => b.getAttribute("data-node-id")),
      ).toEqual(["plan", "build", "docs", "review"]);
    });

    it("lists a loop body's steps under their group node", async () => {
      const user = userEvent.setup();
      const run = anEngineRun({
        steps: [step("fix", 1, 0, 60, "ok"), step("fix__lint", 1, 10, 20, "ok")],
      });
      renderWithApi(<RunDetailScreen />, {
        routes: {
          [`/api/v1/workflow-runs/${run.id}`]: run,
          [WORKFLOW]: aWorkflowDetail({
            layers: [[{ id: "fix", type: "loop_group", depends_on: [], description: null }]],
          }),
        },
        path: `/runs/${run.id}?node=fix`,
        route: "/runs/:runId",
      });

      const panel = await screen.findByRole("complementary", { name: "Node fix" });
      expect(panel).toHaveTextContent("fix__lint");
      const graph = screen.getByRole("group", { name: "Run graph" });
      expect(within(graph).getAllByRole("button")).toHaveLength(1);
      await user.click(within(panel).getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("complementary", { name: "Node fix" })).toBeNull();
    });

    it("measures the graph once while a live run's clock ticks", async () => {
      let observers = 0;
      vi.stubGlobal(
        "ResizeObserver",
        class {
          constructor() {
            observers += 1;
          }
          observe = vi.fn();
          disconnect = vi.fn();
        },
      );
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        const live = anEngineRun({
          ended_at: null,
          status: "running",
          stage: "PICKED",
          failure: null,
        });
        renderWithApi(<RunDetailScreen />, {
          routes: { [`/api/v1/workflow-runs/${live.id}`]: live, [WORKFLOW]: aWorkflowDetail() },
          path: `/runs/${live.id}`,
          route: "/runs/:runId",
        });
        await screen.findByRole("group", { name: "Run graph" });
        const before = observers;
        expect(before).toBeGreaterThan(0);
        await act(async () => {
          await vi.advanceTimersByTimeAsync(3000);
        });
        expect(observers).toBe(before);
      } finally {
        vi.useRealTimers();
      }
    });

    it("decides the run's open gate where the run is watched", async () => {
      const live = anEngineRun({
        ended_at: null,
        status: "running",
        stage: "PICKED",
        failure: null,
      });
      const gateId = `${live.id}:approve-plan:1`;
      const encoded = encodeURIComponent(gateId);
      const own = anApproval({
        id: gateId,
        kind: "human_gate",
        gate_id: gateId,
        session_id: `run:${live.id}`,
        project: live.project,
      });
      const other = anApproval({
        id: "other-run:ship:1",
        kind: "human_gate",
        gate_id: "other-run:ship:1",
        session_id: "run:other-run",
        project: live.project,
      });
      const { requests } = renderWithApi(<RunDetailScreen />, {
        routes: {
          [`/api/v1/workflow-runs/${live.id}`]: live,
          [WORKFLOW]: aWorkflowDetail(),
          "/api/v1/approvals": aPage([own, other]),
          [`/api/v1/approvals/${encoded}/gate`]: {
            approval_id: gateId,
            run_id: live.id,
            project: live.project,
            workflow: "feature-flow",
            node: "approve-plan",
            attempt: 1,
            form: "decision",
            choices: [
              { id: "approve", label: "Approve" },
              { id: "reject", label: "Reject" },
            ],
            text: "off",
          },
          [`POST /api/v1/approvals/${encoded}/decision`]: {
            approval_id: gateId,
            run_id: live.id,
            project: live.project,
            decision: "approve",
          },
        },
        path: `/runs/${live.id}`,
        route: "/runs/:runId",
      });

      const waiting = await screen.findByRole("region", { name: "Waiting for you" });
      expect(within(waiting).getByText("approve-plan")).toBeInTheDocument();
      expect(within(waiting).queryByText("ship")).toBeNull();
      const decide = await within(waiting).findByRole("group", { name: "Decide this gate" });
      await userEvent.click(within(decide).getByRole("button", { name: "Approve" }));

      expect(await within(waiting).findByText(/^Decision recorded/)).toBeInTheDocument();
      const list = requests.find((r) => new URL(r.url).pathname === "/api/v1/approvals");
      const query = new URL(list?.url ?? "http://x").searchParams;
      expect([query.get("kind"), query.get("status"), query.get("project")]).toEqual([
        "human_gate",
        "open",
        live.project,
      ]);
      const post = requests.find((r) => r.method === "POST");
      expect(await post?.json()).toEqual({ decision: "approve" });
    });

    it("shows the decision card in the waiting node's panel", async () => {
      const live = anEngineRun({
        ended_at: null,
        status: "running",
        stage: "PICKED",
        failure: null,
      });
      const gateId = `${live.id}:plan:1`;
      const gate = anApproval({
        id: gateId,
        kind: "human_gate",
        gate_id: gateId,
        session_id: `run:${live.id}`,
        project: live.project,
      });
      renderWithApi(<RunDetailScreen />, {
        routes: {
          [`/api/v1/workflow-runs/${live.id}`]: live,
          [WORKFLOW]: aWorkflowDetail(),
          "/api/v1/approvals": aPage([gate]),
          [`/api/v1/approvals/${encodeURIComponent(gateId)}/gate`]: {
            approval_id: gateId,
            run_id: live.id,
            project: live.project,
            workflow: "feature-flow",
            node: "plan",
            attempt: 1,
            form: "decision",
            choices: [{ id: "approve", label: "Approve" }],
            text: "off",
          },
        },
        path: `/runs/${live.id}?node=plan`,
        route: "/runs/:runId",
      });

      const panel = await screen.findByRole("complementary", { name: "Node plan" });
      expect(await within(panel).findByText(/Waiting for a decision at/)).toBeInTheDocument();
      expect(
        await within(panel).findByRole("group", { name: "Decide this gate" }),
      ).toBeInTheDocument();
      expect(await screen.findByRole("region", { name: "Waiting for you" })).toBeInTheDocument();
    });

    it("shows no open gates and asks for none when the run has ended", async () => {
      const { requests } = renderEngine();

      await screen.findByRole("group", { name: "Run graph" });
      expect(screen.queryByRole("region", { name: "Waiting for you" })).toBeNull();
      expect(requests.some((r) => new URL(r.url).pathname === "/api/v1/approvals")).toBe(false);
    });

    it("keeps issue-to-pr runs on their stage pipeline", async () => {
      renderRun(failedRun);

      await screen.findByRole("list", { name: "Run stages" });
      expect(screen.queryByRole("group", { name: "Run graph" })).toBeNull();
    });

    it("has no serious a11y violations with a node open (a11y)", async () => {
      const { container } = renderEngine(aWorkflowDetail(), "?node=build");

      await screen.findByRole("complementary", { name: "Node build" });
      expect(await seriousViolations(container)).toEqual([]);
    });
  });

  describe("states", () => {
    it("shows the header and pipeline skeleton after 300 ms while pending", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        renderRun("pending");
        await act(async () => {
          await vi.advanceTimersByTimeAsync(350);
        });
        expect(document.querySelectorAll(".ah-skel").length).toBeGreaterThan(8);
      } finally {
        vi.useRealTimers();
      }
    });

    it("shows the not-found page when the run does not exist", async () => {
      renderRun(aProblem({ status: 404, title: "Not found" }));

      expect(
        await screen.findByRole("heading", { name: "Run 01923e08 not found" }),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/It may belong to a hub that is no longer registered\./),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Search with Ctrl K" })).toBeInTheDocument();
    });

    it("shows the problem with Try again when the run cannot be read", async () => {
      renderRun(
        aProblem({ status: 500, title: "Internal error", detail: "Internal error reading steps" }),
      );

      expect(await screen.findByText("Could not load run")).toBeInTheDocument();
      expect(screen.getByText("Internal error reading steps")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    });

    it("stamps the header as stale when the collector is offline", async () => {
      renderRun(failedRun);

      await screen.findByRole("region", { name: "Failure" });
      expect(screen.getByText(/^Stale · as of/)).toBeInTheDocument();
    });
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = renderRun(failedRun);

    await screen.findByRole("region", { name: "Failure" });
    expect(await seriousViolations(container)).toEqual([]);
  });
});
