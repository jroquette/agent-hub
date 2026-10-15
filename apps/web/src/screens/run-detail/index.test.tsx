import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { anId, aProblem, aRun, at, renderWithApi, type WorkflowRun } from "../../testing/builders";
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
