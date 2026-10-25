import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aCapabilities,
  aFindingIssue,
  anAgentSession,
  anApproval,
  anEngineRun,
  anInvestigationSession,
  aPage,
  aProblem,
  aDebugScenarioRun,
  aScenarioDetail,
  aScenarioRunDetail,
  aScenarioRunValues,
  at,
  renderWithApi,
  SCENARIO_RUN,
  type ApiRoutes,
  type ScenarioRunDetail,
} from "../../testing/builders";
import { ScenarioRunScreen } from ".";

const PATH = `/scenarios/demo/order-lifecycle/runs/${SCENARIO_RUN}`;
const RUN = `/api/v1/scenario-runs/${SCENARIO_RUN}`;
const SESSION_ID = anInvestigationSession().agent_session_id;
const SESSION = `/api/v1/agent-sessions/${SESSION_ID}`;
const GATE = `${SCENARIO_RUN}:order-processed__investigation:1`;
const ASK = `${SCENARIO_RUN}:resolve-cover__ask:1`;

const steps = aScenarioDetail({
  steps: [
    ...aScenarioDetail().steps,
    {
      id: "resolve-cover",
      type: "action",
      action: "send-queue-message",
      depends_on: [],
      description: null,
    },
    {
      id: "order-processed",
      type: "expect",
      action: "get-order-by-ref",
      depends_on: [],
      description: null,
    },
  ],
});

const running = anEngineRun({
  id: SCENARIO_RUN,
  workflow: "scenario:order-lifecycle",
  project: "demo",
  status: "running",
  ended_at: null,
  failure: null,
  stage: "PICKED",
});

function gate(id: string, kind: "investigation" | "policy") {
  return anApproval({
    id,
    gate_id: id,
    kind: "human_gate",
    session_id: `run:${SCENARIO_RUN}`,
    project: "demo",
    gate_kind: kind,
    requested_at: at(661),
    path: null,
    rule: null,
  });
}

const routes: ApiRoutes = {
  [RUN]: aScenarioRunDetail(),
  "/api/v1/scenarios/demo/order-lifecycle": steps,
  [`/api/v1/workflow-runs/${SCENARIO_RUN}`]: running,
  "/api/v1/approvals": aPage([gate(GATE, "investigation")]),
  [`POST ${RUN}/investigation`]: anInvestigationSession(),
  "/api/v1/agent-sessions/capabilities": aCapabilities(),
  [SESSION]: anAgentSession({ id: SESSION_ID, status: "idle", last_seq: 0 }),
  [`${SESSION}/events`]: { items: [], next_after: null },
  // A graph run's values: its nodes have no block address.
  [`${RUN}/values`]: aScenarioRunValues({
    inputs: { external_ref: "T-1" },
    blocks: [
      {
        address: null,
        node: "order-processed",
        attempt: 1,
        status: "failed",
        with: { ref: "T-1" },
        output: { status: "OPEN" },
        polls: 2,
        last_poll: { status: "OPEN" },
      },
    ],
  }),
};

function renderRun(extra: ApiRoutes = {}) {
  return renderWithApi(<ScenarioRunScreen />, {
    routes: { ...routes, ...extra },
    path: PATH,
    route: "/scenarios/:project/:name/runs/:runId",
  });
}

const ended: ScenarioRunDetail = aScenarioRunDetail({
  status: "done",
  open_investigation: null,
  paused_step: null,
  timeline: [
    ...aScenarioRunDetail().timeline,
    {
      event: "decision",
      node: "order-processed__investigation",
      attempt: 1,
      status: null,
      at: at(1000),
    },
    { event: "workaround_start", node: null, attempt: 1, status: null, at: at(1001) },
    { event: "workaround_end", node: null, attempt: 1, status: "ok", at: at(1100) },
    { event: "step_start", node: "order-processed", attempt: 2, status: null, at: at(1101) },
    { event: "step_end", node: "order-processed", attempt: 2, status: "ok", at: at(1200) },
    { event: "end", node: null, attempt: null, status: "done", at: at(1201) },
  ],
  investigations: [
    {
      number: 1,
      step: "order-processed",
      gate: "order-processed__investigation",
      failure_kind: "timeout",
      agent_session_id: null,
      choice: "pick",
      text: "o2",
      approver: "Dana Demo",
      closed: true,
    },
  ],
  workarounds: [
    { workaround_id: "w1", number: 1, option: "o2", steps: 1, approver: "Dana Demo", status: "ok" },
  ],
});

afterEach(() => {
  window.localStorage.clear();
});

describe("ScenarioRunScreen (scenarios run)", () => {
  it("scenarios run shows steps, polls, captures, decisions, findings and workarounds", async () => {
    renderRun({
      [RUN]: ended,
      [`/api/v1/workflow-runs/${SCENARIO_RUN}`]: { ...running, status: "done" },
    });

    const timeline = await screen.findByRole("region", { name: "Timeline" });
    await within(timeline).findByText(/action send-queue-message/);
    const text = timeline.textContent;
    expect(text).toContain("Started in personal · interactive");
    expect(text).toContain("fetch-order · action send-queue-message · ok");
    expect(text).toContain("order-on-hold · 3 polls · held");
    expect(text).toContain("captured order_id = 81234");
    expect(text).toContain("resolve-cover__ask · approved by Dana Demo in hub web");
    expect(text).toContain("order-processed · 2 polls · never held · failed: timeout");
    expect(text).toContain("Investigation 1 opened at order-processed");
    expect(text).toContain("Investigation read: orders/get-order (read) · ok");
    expect(text).toContain("Proposal 2: 1 finding, 3 options");
    expect(text).toContain("Workaround 1 started: option o2, 1 step, picked by Dana Demo");
    expect(text).toContain("Workaround 1 ended ok");
    expect(text).toContain("order-processed · attempt 2");
    expect(screen.getByText(/^Done at .* · 3 steps · 1 workaround$/)).toBeInTheDocument();
    const findings = screen.getByRole("region", { name: "Findings" });
    expect(findings).toHaveTextContent("f1 · Collection orders lack tracking");
    expect(findings).toHaveTextContent("step order-processed in personal");
    const facts = screen.getByRole("complementary", { name: "Scenario run facts" });
    expect(facts).toHaveTextContent("Investigations1 of at most 10");
    expect(facts).toHaveTextContent("Capturesorder_id = 81234");
    await userEvent.click(within(timeline).getByText(/Workaround 1 ended ok/));
    expect(
      within(timeline)
        .getByText(/Workaround 1 ended ok/)
        .closest(".ah-ev"),
    ).toHaveAttribute("aria-current", "true");
    // No chat and no options once the pause is over.
    expect(screen.queryByRole("region", { name: "Investigation chat" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Cancel/ })).toBeNull();
  });

  it("scenarios run paused shows the chat, the options with their plans and the pick", async () => {
    const user = userEvent.setup();
    const { requests, router } = renderRun({
      [`POST ${RUN}/answer`]: {
        run_id: SCENARIO_RUN,
        project: "demo",
        investigation: 1,
        step: "order-processed",
        choice: "pick",
        option: "o2",
      },
    });

    const banner = await screen.findByRole("region", { name: "Paused at order-processed" });
    expect(banner).toHaveTextContent(
      "Paused at order-processed: it did not reach its expected state before its timeout (2 polls in 10 min).",
    );
    expect(banner).toHaveTextContent("Steps that did not depend on it have run.");
    const chat = screen.getByRole("region", { name: "Investigation chat" });
    expect(chat).toHaveTextContent("Investigation 1 · read-only agent");
    expect(chat).toHaveTextContent("Run read actions in personal.");
    expect(chat).toHaveTextContent("These limits hold its tools; they are not a sandbox.");
    expect(
      await within(chat).findByRole("textbox", { name: "Message Claude" }),
    ).toBeInTheDocument();
    // The investigation session keeps its mode: no switch (E-15).
    expect(within(chat).queryByRole("combobox", { name: "Mode" })).toBeNull();
    expect(
      requests.filter((r) => r.method === "POST" && r.url.endsWith("/investigation")),
    ).toHaveLength(1);
    // The top bar's Discuss is not on this page; nor are run commands while paused.
    expect(screen.queryByRole("button", { name: /Cancel/ })).toBeNull();

    const options = screen.getByRole("radiogroup", { name: "Options from the agent" });
    const radios = within(options).getAllByRole("radio");
    expect(radios).toHaveLength(3);
    const refused = within(options).getByRole("radio", { name: "o3 · Render the invoice PDF" });
    expect(refused).toBeDisabled();
    expect(refused).toHaveAccessibleDescription(
      "Cannot be picked: step 1 (orders/render-invoice-pdf): draft action: commit it to run.",
    );
    expect(within(options).getAllByRole("table")).toHaveLength(3);
    expect(within(options).getByText("orders/regenerate-shipments")).toBeInTheDocument();
    expect(
      within(options).getByRole("button", { name: /Copy the commit command/ }),
    ).toBeInTheDocument();

    expect(screen.getByRole("button", { name: "Pick an option" })).toBeDisabled();
    await user.click(within(options).getByRole("radio", { name: "o2 · Regenerate the shipments" }));
    expect(router.state.location.search).toBe("?option=o2");
    await user.click(screen.getByRole("button", { name: "Pick option o2" }));
    const dialog = screen.getByRole("alertdialog", {
      name: "Pick option o2 and run it in personal?",
    });
    expect(dialog).toHaveTextContent(
      "Its 1 step runs in personal as a workaround by the agent: orders/regenerate-shipments (destroy). Picking it is your approval of that step. Then order-processed runs again. Nothing is rewound.",
    );
    expect(within(dialog).getByRole("button", { name: "Back to options" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Pick option o2" }));

    expect(
      await screen.findByText(
        "Answer recorded: option o2 picked. The scenario run resumes; its events update this page.",
      ),
    ).toBeInTheDocument();
    const answer = requests.find((r) => r.method === "POST" && r.url.endsWith("/answer"));
    expect(await answer?.clone().json()).toEqual({ choice: "pick", option: "o2" });
  });

  it("scenarios run refuses a pick with its reason", async () => {
    const user = userEvent.setup();
    renderRun({
      [`POST ${RUN}/answer`]: aProblem({
        status: 409,
        title: "Workflow run command refused",
        detail:
          "option o1 cannot be picked: the plan of step 1 (orders/patch-order) changed since it was shown; ask for a new proposal",
        code: "pick_refused",
      }),
    });
    const options = await screen.findByRole("radiogroup", { name: "Options from the agent" });
    await user.click(
      within(options).getByRole("radio", { name: "o1 · Set the order's carrier, then reprocess" }),
    );
    await user.click(screen.getByRole("button", { name: "Pick option o1" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Pick option o1" }),
    );

    const refusal = await screen.findByText("Option o1 was not picked");
    const alert = refusal.closest("[role=alert]");
    expect(alert).toHaveTextContent(
      "option o1 cannot be picked: the plan of step 1 (orders/patch-order) changed since it was shown; ask for a new proposal",
    );
    expect(alert).toHaveTextContent("Nothing was recorded.");
    // The selection is kept.
    expect(within(options).getByRole("radio", { name: /o1/ })).toBeChecked();
  });

  it("scenarios run retries and stops the step behind confirms", async () => {
    const user = userEvent.setup();
    const { requests } = renderRun({
      [`POST ${RUN}/answer`]: (request: Request) => ({
        run_id: SCENARIO_RUN,
        project: "demo",
        investigation: 1,
        step: "order-processed",
        choice: request.url.includes("answer") ? "retry" : "stop",
        option: null,
      }),
    });
    await user.click(await screen.findByRole("button", { name: "Stop scenario run" }));
    const stop = screen.getByRole("alertdialog", { name: "Stop this scenario run?" });
    expect(stop).toHaveTextContent(
      "It ends cancelled. Its findings are kept, nothing is rewound, and it cannot be resumed.",
    );
    expect(within(stop).getByRole("button", { name: "Keep scenario run" })).toHaveFocus();
    await user.click(within(stop).getByRole("button", { name: "Keep scenario run" }));

    await user.click(screen.getByRole("button", { name: "Retry order-processed" }));
    const retry = screen.getByRole("alertdialog", { name: "Retry order-processed in personal?" });
    expect(retry).toHaveTextContent(
      "If it diverges again, a new investigation opens (2 of at most 10).",
    );
    await user.click(within(retry).getByRole("button", { name: "Retry order-processed" }));
    expect(
      await screen.findAllByText("Answer recorded: order-processed runs again."),
    ).not.toHaveLength(0);
    const sent = requests.find((r) => r.method === "POST" && r.url.endsWith("/answer"));
    expect(await sent?.clone().json()).toEqual({ choice: "retry" });
    // While answered, the three answers are off.
    expect(screen.getByRole("button", { name: "Stop scenario run" })).toBeDisabled();
  });

  it("scenarios run answers a policy ask in its Waiting for you card", async () => {
    renderRun({
      [RUN]: aScenarioRunDetail({
        open_investigation: null,
        paused_step: null,
        investigations: [],
        proposal: null,
      }),
      "/api/v1/approvals": aPage([gate(GATE, "investigation"), gate(ASK, "policy")]),
      [`/api/v1/approvals/${encodeURIComponent(ASK)}/gate`]: {
        approval_id: ASK,
        run_id: SCENARIO_RUN,
        project: "demo",
        workflow: "scenario:order-lifecycle",
        node: "resolve-cover__ask",
        attempt: 1,
        form: "decision",
        choices: [
          { id: "approve", label: "Approve" },
          { id: "reject", label: "Reject" },
        ],
        text: "off",
      },
    });

    const card = await screen.findByRole("region", { name: "Waiting for you" });
    expect(card).toHaveTextContent("resolve-cover__ask waits for your approval since");
    expect(card).toHaveTextContent("Reject cancels the scenario run.");
    expect(card).not.toHaveTextContent("order-processed__investigation");
    expect(await within(card).findByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Reject" })).toBeInTheDocument();
    // A running scenario run not paused at an investigation offers Cancel only.
    expect(screen.getByRole("button", { name: "Cancel scenario run" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Resume/ })).toBeNull();
  });

  it("scenarios run drafts a finding's issue, then creates it once", async () => {
    const user = userEvent.setup();
    const { requests } = renderRun({
      [`POST ${RUN}/findings/f1/issue`]: (request: Request) =>
        request.headers.get("content-length") === "2" ? aFindingIssue() : aFindingIssue(),
    });
    const findings = await screen.findByRole("region", { name: "Findings" });
    await user.click(within(findings).getByRole("button", { name: "Draft tracker issue" }));

    const dialog = await screen.findByRole("dialog", { name: "Create an issue for finding f1?" });
    expect(dialog).toHaveTextContent("Goes to team DEMO.");
    expect(dialog).toHaveTextContent(
      "It is created once. If the create fails, it is not retried here.",
    );
    const sent = requests.filter((r) => r.method === "POST" && r.url.endsWith("/issue"));
    expect(await sent[0]?.clone().json()).toEqual({ confirm: false });
  });

  it("scenarios run creates a finding's issue and never retries a failed create", async () => {
    const user = userEvent.setup();
    let calls = 0;
    const { requests } = renderRun({
      [`POST ${RUN}/findings/f1/issue`]: () => {
        calls += 1;
        return calls === 1
          ? aFindingIssue()
          : aProblem({ status: 502, title: "Could not create the tracker issue" });
      },
    });
    const findings = await screen.findByRole("region", { name: "Findings" });
    await user.click(within(findings).getByRole("button", { name: "Draft tracker issue" }));
    const dialog = await screen.findByRole("dialog", { name: "Create an issue for finding f1?" });
    await user.click(within(dialog).getByRole("button", { name: "Create issue in DEMO" }));

    expect(
      await screen.findByText("The issue may already exist in the tracker"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(`./hub scenario findings ${SCENARIO_RUN} --issue f1`),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Create issue in DEMO" })).toBeDisabled();
    const posted = requests.filter((r) => r.method === "POST" && r.url.endsWith("/issue"));
    expect(posted).toHaveLength(2);
    expect(await posted[1]?.clone().json()).toEqual({ confirm: true });
  });

  it("scenarios run writes a finding's inbox note", async () => {
    const user = userEvent.setup();
    renderRun({
      [`POST ${RUN}/findings/f1/inbox`]: {
        run_id: SCENARIO_RUN,
        finding_id: "f1",
        path: "brain/_inbox/2026-10-22-scenario-order-lifecycle-f1.md",
      },
    });
    const findings = await screen.findByRole("region", { name: "Findings" });
    await user.click(within(findings).getByRole("button", { name: "Write inbox note" }));

    expect(await within(findings).findByText(/^Wrote /)).toHaveTextContent(
      "Wrote brain/_inbox/2026-10-22-scenario-order-lifecycle-f1.md.",
    );
  });

  describe("states", () => {
    it("scenarios run states: not found", async () => {
      renderRun({ [RUN]: aProblem({ status: 404, title: "Not found" }) });

      expect(await screen.findByText(`Scenario run ${SCENARIO_RUN} not found`)).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Go to Scenarios" })).toHaveAttribute(
        "href",
        "/scenarios",
      );
    });

    it("scenarios run states: record too large", async () => {
      renderRun({
        [RUN]: aProblem({
          status: 422,
          title: "Scenario run record unreadable",
          code: "record_too_large",
        }),
      });

      expect(
        await screen.findByText("This scenario run's record is too large to read here"),
      ).toBeInTheDocument();
      expect(screen.getByText(`./hub scenario findings ${SCENARIO_RUN}`)).toBeInTheDocument();
    });

    it("scenarios run states: the session cannot be reopened, the answers still work", async () => {
      renderRun({
        [`POST ${RUN}/investigation`]: aProblem({
          status: 409,
          title: "Agent session not reopened",
          type: "urn:agent-hub:problem:agent-session-restriction-unavailable",
        }),
      });

      expect(
        await screen.findByText(
          "The investigation session cannot be reopened with its limits, so it stays closed.",
        ),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Retry order-processed" })).toBeEnabled();
    });

    it("scenarios run states: a failed scenario run in regression mode", async () => {
      renderRun({
        [RUN]: aScenarioRunDetail({
          mode: "regression",
          status: "failed",
          open_investigation: null,
          paused_step: null,
          investigations: [],
          proposal: null,
          findings: [],
          timeline: [
            ...aScenarioRunDetail().timeline.slice(0, 9),
            { event: "end", node: null, attempt: null, status: "failed", at: at(661) },
          ],
        }),
      });

      expect(
        await screen.findByText(
          "Failed at order-processed: it did not reach its expected state before its timeout. Regression mode: no investigation.",
        ),
      ).toBeInTheDocument();
      expect(screen.getByText("No findings recorded.")).toBeInTheDocument();
    });
  });

  it("scenarios run paused has no serious a11y violation (a11y)", { timeout: 20_000 }, async () => {
    const { container } = renderRun();
    await screen.findByRole("radiogroup", { name: "Options from the agent" });
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Message Claude" })).toBeInTheDocument();
    });

    expect(await seriousViolations(container)).toEqual([]);
  });

  it("scenarios run ended has no serious a11y violation (a11y)", async () => {
    const { container } = renderRun({ [RUN]: ended });
    await screen.findByRole("region", { name: "Timeline" });

    expect(await seriousViolations(container)).toEqual([]);
  });
  it("scenarios run in the container: the answers and finding actions are off, the command names the recorded gate", async () => {
    const recorded = "intake__order-processed__investigation";
    renderRun({
      [RUN]: aScenarioRunDetail({
        investigations: [
          {
            ...aScenarioRunDetail().investigations[0],
            gate: recorded,
          } as ScenarioRunDetail["investigations"][number],
        ],
      }),
      [`POST ${RUN}/investigation`]: aProblem({
        status: 404,
        title: "Run control off",
        type: "urn:agent-hub:problem:run-control-off",
      }),
    });

    expect(
      await screen.findAllByText(
        "This scenario run cannot be answered from the agent-hub container",
      ),
    ).not.toHaveLength(0);
    expect(
      screen.getAllByText(
        `./hub workflow respond ${SCENARIO_RUN} --node ${recorded} --choice retry`,
      ),
    ).not.toHaveLength(0);
    expect(screen.queryByText(/--node order-processed__investigation/)).toBeNull();
    expect(screen.getByRole("button", { name: "Retry order-processed" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Stop scenario run" })).toBeDisabled();
    const findings = screen.getByRole("region", { name: "Findings" });
    expect(within(findings).getByRole("button", { name: "Draft tracker issue" })).toBeDisabled();
    expect(within(findings).getByRole("button", { name: "Write inbox note" })).toBeDisabled();
  });
  it("scenarios run says Waiting for you while a policy ask holds it", async () => {
    renderRun({
      [RUN]: aScenarioRunDetail({
        open_investigation: null,
        paused_step: null,
        investigations: [],
        proposal: null,
      }),
      "/api/v1/approvals": aPage([gate(ASK, "policy")]),
    });

    const heading = await screen.findByRole("heading", { level: 1 });
    await waitFor(() => {
      expect(heading.parentElement).toHaveTextContent("Waiting for you");
    });
  });

  it("scenarios run after an answer: a toast, a resuming line until the run moves on, focus on the heading", async () => {
    const user = userEvent.setup();
    const gateNode = "order-processed__investigation";
    let stage: "paused" | "answered" | "moved" = "paused";
    // As fold_records reads the record once the answer is recorded and its gate closed (B3).
    const answeredRecord = (): ScenarioRunDetail => {
      const base = aScenarioRunDetail();
      return {
        ...base,
        open_investigation: null,
        paused_step: null,
        timeline: [
          ...base.timeline,
          { event: "decision", node: gateNode, attempt: 1, status: null, at: at(1000) },
          { event: "step_end", node: gateNode, attempt: 1, status: "ok", at: at(1000) },
          { event: "workaround_start", node: null, attempt: 1, status: null, at: at(1001) },
          // A gate's own start never moves the run on (review round 3, Q2).
          { event: "step_start", node: gateNode, attempt: 2, status: null, at: at(1002) },
          ...(stage === "moved"
            ? [
                {
                  event: "step_start",
                  node: "order-processed",
                  attempt: 2,
                  status: null,
                  at: at(1100),
                },
              ]
            : []),
        ],
        decisions: [
          ...base.decisions,
          {
            node: gateNode,
            attempt: 1,
            choice: "pick",
            text: "o2",
            approver: "Dana Demo",
            where: "web",
            at: at(1000),
          },
        ],
        investigations: [
          {
            number: 1,
            step: "order-processed",
            gate: gateNode,
            failure_kind: "timeout",
            agent_session_id: null,
            choice: "pick",
            text: "o2",
            approver: "Dana Demo",
            closed: true,
          },
        ],
        workarounds: [
          {
            workaround_id: "w1",
            number: 1,
            option: "o2",
            steps: 1,
            approver: "Dana Demo",
            status: null,
          },
        ],
      };
    };
    const { queryClient } = renderRun({
      [RUN]: () => (stage === "paused" ? aScenarioRunDetail() : answeredRecord()),
      [`POST ${RUN}/answer`]: () => {
        stage = "answered";
        return {
          run_id: SCENARIO_RUN,
          project: "demo",
          investigation: 1,
          step: "order-processed",
          choice: "pick",
          option: "o2",
        };
      },
    });
    const options = await screen.findByRole("radiogroup", { name: "Options from the agent" });
    const announcer = document.querySelector("[data-announcer]");
    expect(announcer).toHaveTextContent("Scenario run paused at order-processed");
    await user.click(within(options).getByRole("radio", { name: /o2/ }));
    await user.click(screen.getByRole("button", { name: "Pick option o2" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Pick option o2" }),
    );

    expect(await screen.findByText("Answer recorded: option o2 picked.")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Paused at order-processed" })).toBeNull();
    });
    const resuming =
      "Answer recorded: option o2 picked. The scenario run resumes; its events update this page.";
    expect(screen.getByText(resuming)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveFocus();
    expect(announcer).toHaveTextContent("Answer recorded");
    // One live announcement: the toast and the lines are plain text (N2).
    expect(
      screen.queryAllByRole("status").filter((el) => el.textContent.includes("Answer recorded")),
    ).toHaveLength(0);

    stage = "moved";
    await act(async () => {
      await queryClient.invalidateQueries();
    });
    await waitFor(() => {
      expect(screen.queryByText(resuming)).toBeNull();
    });
  });

  it("scenarios run announces the end and keeps the answer bar above sticky table heads", async () => {
    const { unmount } = renderRun();
    const bar = await screen.findByRole("group", { name: "Answer" });
    expect(bar.style.zIndex).not.toBe("");
    expect(bar.style.borderTop).not.toBe("");
    unmount();

    renderRun({ [RUN]: ended });
    await screen.findByRole("region", { name: "Timeline" });
    expect(document.querySelector("[data-announcer]")).toHaveTextContent("Scenario run done");
  });

  it("scenarios run shows a captured credential as a redaction chip and names the approver", async () => {
    renderRun({
      [RUN]: {
        ...ended,
        captures: [
          { node: "order-on-hold", attempt: 1, name: "db_url", value: "<credential DEMO_DB_URL>" },
        ],
      },
    });

    const timeline = await screen.findByRole("region", { name: "Timeline" });
    expect(
      await within(timeline).findByText("[redacted: credential DEMO_DB_URL]"),
    ).toBeInTheDocument();
    expect(within(timeline).getAllByText("Dana Demo").length).toBeGreaterThan(0);
  });

  it("scenarios run puts an option's draft line in a full-width row of its plan", async () => {
    renderRun();
    const options = await screen.findByRole("radiogroup", { name: "Options from the agent" });

    const table = within(options).getByRole("table", { name: "Plan of option o3" });
    const draftRow = within(table).getByText("Draft: needs acceptance").closest("tr");
    expect(draftRow?.querySelector("td")).toHaveAttribute("colspan", "2");
    expect(table).toHaveClass("sc-plan");
  });
  it("scenarios run splits a captured value on its credential marks", async () => {
    renderRun({
      [RUN]: {
        ...ended,
        captures: [
          {
            node: "order-on-hold",
            attempt: 1,
            name: "db_url",
            value:
              "postgres://<credential DEMO_DB_USER>:<credential DEMO_DB_PASS>@db.example.com/x",
          },
        ],
      },
    });

    const timeline = await screen.findByRole("region", { name: "Timeline" });
    expect(
      await within(timeline).findByText("[redacted: credential DEMO_DB_USER]"),
    ).toBeInTheDocument();
    expect(within(timeline).getByText("[redacted: credential DEMO_DB_PASS]")).toBeInTheDocument();
    expect(timeline).toHaveTextContent("postgres://");
    expect(timeline).toHaveTextContent("@db.example.com/x");
    expect(timeline).not.toHaveTextContent("<credential");
    const facts = screen.getByRole("complementary", { name: "Scenario run facts" });
    expect(within(facts).getByText("[redacted: credential DEMO_DB_PASS]")).toBeInTheDocument();
  });
  it("scenarios run lays an option's step out on two lines: step and policy, then effect and where", async () => {
    renderRun();
    const options = await screen.findByRole("radiogroup", { name: "Options from the agent" });

    const table = within(options).getByRole("table", { name: "Plan of option o1" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((th) => th.textContent),
    ).toEqual(["Step", "Policy"]);
    const step = within(table).getByText("orders/patch-order", { exact: false }).closest("td");
    expect(step).toHaveTextContent(/orders\/patch-order.*write.*demo-api\/orders-db/);
    // Ids break only after "/" or "-".
    expect(step?.querySelectorAll("wbr").length).toBeGreaterThan(0);
  });
  describe("after an answer (round 3)", () => {
    const gateNode = "order-processed__investigation";
    const answer = {
      run_id: SCENARIO_RUN,
      project: "demo",
      investigation: 1,
      step: "order-processed",
      choice: "pick",
      option: "o2",
    };
    const closedFirst = {
      number: 1,
      step: "order-processed",
      gate: gateNode,
      failure_kind: "timeout",
      agent_session_id: null,
      choice: "pick",
      text: "o2",
      approver: "Dana Demo",
      closed: true,
    };

    async function pickO2() {
      const fake = vi.isFakeTimers();
      const user = userEvent.setup(
        fake ? { advanceTimers: (ms: number) => vi.advanceTimersByTime(ms) } : {},
      );
      const options = await screen.findByRole("radiogroup", { name: "Options from the agent" });
      await user.click(within(options).getByRole("radio", { name: /o2/ }));
      await user.click(screen.getByRole("button", { name: "Pick option o2" }));
      await user.click(
        within(screen.getByRole("alertdialog")).getByRole("button", { name: "Pick option o2" }),
      );
    }

    it("scenarios run announces a new pause when a failed workaround reopens the investigation", async () => {
      let stage: "paused" | "reopened" = "paused";
      const base = aScenarioRunDetail();
      const { queryClient } = renderRun({
        [RUN]: () =>
          stage === "paused"
            ? base
            : {
                ...base,
                open_investigation: 2,
                paused_step: "order-processed",
                timeline: [
                  ...base.timeline,
                  { event: "decision", node: gateNode, attempt: 1, status: null, at: at(1000) },
                  { event: "step_end", node: gateNode, attempt: 1, status: "ok", at: at(1000) },
                  { event: "workaround_start", node: null, attempt: 1, status: null, at: at(1001) },
                  {
                    event: "workaround_end",
                    node: null,
                    attempt: 1,
                    status: "failed",
                    at: at(1050),
                  },
                  {
                    event: "investigation",
                    node: "order-processed",
                    attempt: 2,
                    status: null,
                    at: at(1051),
                  },
                  { event: "gate", node: gateNode, attempt: 2, status: null, at: at(1051) },
                ],
                investigations: [
                  closedFirst,
                  {
                    ...closedFirst,
                    number: 2,
                    choice: null,
                    text: null,
                    approver: null,
                    closed: false,
                  },
                ],
                proposal: null,
                workarounds: [
                  {
                    workaround_id: "w1",
                    number: 1,
                    option: "o2",
                    steps: 1,
                    approver: "Dana Demo",
                    status: "failed",
                  },
                ],
              },
        [`POST ${RUN}/answer`]: () => {
          stage = "reopened";
          return answer;
        },
      });
      await pickO2();
      const announcer = document.querySelector("[data-announcer]");
      // The answer was recorded here (its toast shows), then the record reopened the pause.
      expect(await screen.findByText("Answer recorded: option o2 picked.")).toBeInTheDocument();
      await act(async () => {
        await queryClient.invalidateQueries();
      });

      await waitFor(() => {
        expect(announcer).toHaveTextContent("Scenario run paused at order-processed");
      });
      expect(screen.getByRole("region", { name: "Paused at order-processed" })).toBeInTheDocument();
      expect(
        screen.queryByText(
          "Answer recorded: option o2 picked. The scenario run resumes; its events update this page.",
        ),
      ).toBeNull();
    });

    it("scenarios run makes one live announcement while the options are still shown", async () => {
      renderRun({ [`POST ${RUN}/answer`]: answer });
      await pickO2();
      const announcer = document.querySelector("[data-announcer]");

      await waitFor(() => {
        expect(announcer).toHaveTextContent("Answer recorded");
      });
      expect(
        screen.getByRole("radiogroup", { name: "Options from the agent" }),
      ).toBeInTheDocument();
      const live = [
        ...document.querySelectorAll('[role="status"], [role="alert"], [aria-live]'),
      ].filter((el) => el.textContent.includes("Answer recorded"));
      expect(live).toEqual([announcer]);
    });

    it("scenarios run's answer toast ends after 6000 ms", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        renderRun({ [`POST ${RUN}/answer`]: answer });
        await pickO2();
        expect(await screen.findByText("Answer recorded: option o2 picked.")).toBeInTheDocument();

        act(() => {
          vi.advanceTimersByTime(5900);
        });
        expect(screen.getByText("Answer recorded: option o2 picked.")).toBeInTheDocument();
        act(() => {
          vi.advanceTimersByTime(6000);
        });
        expect(screen.queryByText("Answer recorded: option o2 picked.")).toBeNull();
      } finally {
        vi.useRealTimers();
      }
    });
  });
  it("scenarios run starts a reopened investigation with nothing picked and focus on the heading", async () => {
    const user = userEvent.setup();
    const gateNode = "order-processed__investigation";
    let stage: "paused" | "reopened" = "paused";
    const base = aScenarioRunDetail();
    const { router, queryClient } = renderRun({
      [RUN]: () =>
        stage === "paused"
          ? base
          : {
              ...base,
              open_investigation: 2,
              timeline: [
                ...base.timeline,
                { event: "decision", node: gateNode, attempt: 1, status: null, at: at(1000) },
                { event: "step_end", node: gateNode, attempt: 1, status: "ok", at: at(1000) },
                {
                  event: "investigation",
                  node: "order-processed",
                  attempt: 2,
                  status: null,
                  at: at(1051),
                },
                { event: "gate", node: gateNode, attempt: 2, status: null, at: at(1051) },
              ],
              investigations: [
                {
                  ...base.investigations[0],
                  choice: "pick",
                  text: "o1",
                  closed: true,
                } as ScenarioRunDetail["investigations"][number],
                {
                  ...base.investigations[0],
                  number: 2,
                } as ScenarioRunDetail["investigations"][number],
              ],
              // The new proposal reuses the ids: o1 is the option that just failed.
              proposal: { proposal: 3, investigation: 2, options: base.proposal?.options ?? [] },
            },
      [`POST ${RUN}/answer`]: () => {
        stage = "reopened";
        return {
          run_id: SCENARIO_RUN,
          project: "demo",
          investigation: 1,
          step: "order-processed",
          choice: "pick",
          option: "o1",
        };
      },
    });
    const options = await screen.findByRole("radiogroup", { name: "Options from the agent" });
    await user.click(within(options).getByRole("radio", { name: /o1 ·/ }));
    await user.click(screen.getByRole("button", { name: "Pick option o1" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Pick option o1" }),
    );
    await screen.findByText("Answer recorded: option o1 picked.");
    await act(async () => {
      await queryClient.invalidateQueries();
    });

    await waitFor(() => {
      expect(screen.getByText("proposal 3")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(router.state.location.search).toBe("");
    });
    const reopened = screen.getByRole("radiogroup", { name: "Options from the agent" });
    expect(within(reopened).queryAllByRole("radio", { checked: true })).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Pick an option" })).toBeDisabled();
    expect(screen.getByRole("heading", { level: 1 })).toHaveFocus();
  });
  it("scenarios run starts an investigation reopened across a running state with nothing picked", async () => {
    const user = userEvent.setup();
    const gateNode = "order-processed__investigation";
    let stage: "paused" | "running" | "reopened" = "paused";
    const base = aScenarioRunDetail();
    const answeredFirst = {
      ...base.investigations[0],
      choice: "pick",
      text: "o1",
      closed: true,
    } as ScenarioRunDetail["investigations"][number];
    const runningTimeline = [
      ...base.timeline,
      { event: "decision", node: gateNode, attempt: 1, status: null, at: at(1000) },
      { event: "step_end", node: gateNode, attempt: 1, status: "ok", at: at(1000) },
      { event: "workaround_start", node: null, attempt: 1, status: null, at: at(1001) },
    ];
    const { router, queryClient } = renderRun({
      [RUN]: () => {
        if (stage === "paused") return base;
        if (stage === "running") {
          // Between the answer and the next pause the run is running: no open investigation.
          return {
            ...base,
            open_investigation: null,
            paused_step: null,
            timeline: runningTimeline,
            investigations: [answeredFirst],
          };
        }
        return {
          ...base,
          open_investigation: 2,
          timeline: [
            ...runningTimeline,
            { event: "workaround_end", node: null, attempt: 1, status: "failed", at: at(1050) },
            {
              event: "investigation",
              node: "order-processed",
              attempt: 2,
              status: null,
              at: at(1051),
            },
            { event: "gate", node: gateNode, attempt: 2, status: null, at: at(1051) },
          ],
          investigations: [
            answeredFirst,
            { ...base.investigations[0], number: 2 } as ScenarioRunDetail["investigations"][number],
          ],
          // The new proposal reuses the ids: o1 is the option that just failed.
          proposal: { proposal: 3, investigation: 2, options: base.proposal?.options ?? [] },
        };
      },
      [`POST ${RUN}/answer`]: () => {
        stage = "running";
        return {
          run_id: SCENARIO_RUN,
          project: "demo",
          investigation: 1,
          step: "order-processed",
          choice: "pick",
          option: "o1",
        };
      },
    });
    const options = await screen.findByRole("radiogroup", { name: "Options from the agent" });
    await user.click(within(options).getByRole("radio", { name: /o1 ·/ }));
    await user.click(screen.getByRole("button", { name: "Pick option o1" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Pick option o1" }),
    );
    await screen.findByText("Answer recorded: option o1 picked.");
    await waitFor(() => {
      expect(screen.queryByRole("radiogroup", { name: "Options from the agent" })).toBeNull();
    });

    stage = "reopened";
    await act(async () => {
      await queryClient.invalidateQueries();
    });

    await waitFor(() => {
      expect(screen.getByText("proposal 3")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(router.state.location.search).toBe("");
    });
    await waitFor(() => {
      const reopened = screen.getByRole("radiogroup", { name: "Options from the agent" });
      expect(within(reopened).queryAllByRole("radio", { checked: true })).toHaveLength(0);
    });
    expect(screen.getByRole("button", { name: "Pick an option" })).toBeDisabled();
    expect(screen.getByRole("heading", { level: 1 })).toHaveFocus();
  });

  it("scenarios run starts an investigation reopened across a running state with nothing picked on its first paint", async () => {
    const user = userEvent.setup();
    const gateNode = "order-processed__investigation";
    let stage: "paused" | "running" | "reopened" = "paused";
    const base = aScenarioRunDetail();
    const answeredFirst = {
      ...base.investigations[0],
      choice: "pick",
      text: "o1",
      closed: true,
    } as ScenarioRunDetail["investigations"][number];
    const runningTimeline = [
      ...base.timeline,
      { event: "decision", node: gateNode, attempt: 1, status: null, at: at(1000) },
      { event: "step_end", node: gateNode, attempt: 1, status: "ok", at: at(1000) },
      { event: "workaround_start", node: null, attempt: 1, status: null, at: at(1001) },
    ];
    const { router, queryClient } = renderRun({
      [RUN]: () => {
        if (stage === "paused") return base;
        if (stage === "running") {
          // Between the answer and the next pause the run is running: no open investigation.
          return {
            ...base,
            open_investigation: null,
            paused_step: null,
            timeline: runningTimeline,
            investigations: [answeredFirst],
          };
        }
        return {
          ...base,
          open_investigation: 2,
          timeline: [
            ...runningTimeline,
            { event: "workaround_end", node: null, attempt: 1, status: "failed", at: at(1050) },
            {
              event: "investigation",
              node: "order-processed",
              attempt: 2,
              status: null,
              at: at(1051),
            },
            { event: "gate", node: gateNode, attempt: 2, status: null, at: at(1051) },
          ],
          investigations: [
            answeredFirst,
            { ...base.investigations[0], number: 2 } as ScenarioRunDetail["investigations"][number],
          ],
          // The new proposal reuses the ids: o1 is the option that just failed.
          proposal: { proposal: 3, investigation: 2, options: base.proposal?.options ?? [] },
        };
      },
      [`POST ${RUN}/answer`]: () => {
        stage = "running";
        return {
          run_id: SCENARIO_RUN,
          project: "demo",
          investigation: 1,
          step: "order-processed",
          choice: "pick",
          option: "o1",
        };
      },
    });
    const options = await screen.findByRole("radiogroup", { name: "Options from the agent" });
    await user.click(within(options).getByRole("radio", { name: /o1 ·/ }));
    await user.click(screen.getByRole("button", { name: "Pick option o1" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Pick option o1" }),
    );
    await screen.findByText("Answer recorded: option o1 picked.");
    await waitFor(() => {
      expect(screen.queryByRole("radiogroup", { name: "Options from the agent" })).toBeNull();
    });

    // What the first paint of the reopened investigation shows, before any later effect runs.
    let firstPaint: { checked: number; bar: string | null } | null = null;
    const observer = new MutationObserver(() => {
      if (firstPaint !== null || screen.queryByText("proposal 3") === null) return;
      const group = screen.queryByRole("radiogroup", { name: "Options from the agent" });
      const bar = screen.queryByRole("button", { name: /^Pick / });
      firstPaint = {
        checked: group ? within(group).queryAllByRole("radio", { checked: true }).length : -1,
        bar: bar
          ? `${bar.textContent}${(bar as HTMLButtonElement).disabled ? " (disabled)" : ""}`
          : null,
      };
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true });
    stage = "reopened";
    await act(async () => {
      await queryClient.invalidateQueries();
    });
    expect(await screen.findByText("proposal 3")).toBeInTheDocument();
    observer.disconnect();

    expect(firstPaint).toEqual({ checked: 0, bar: "Pick an option (disabled)" });
    expect(router.state.location.search).toBe("");
  });

  it("scenarios run starts an investigation reopened across a running state with a pick made before the cleared URL lands", async () => {
    const user = userEvent.setup();
    const gateNode = "order-processed__investigation";
    let stage: "paused" | "running" | "reopened" = "paused";
    const base = aScenarioRunDetail();
    const answeredFirst = {
      ...base.investigations[0],
      choice: "pick",
      text: "o1",
      closed: true,
    } as ScenarioRunDetail["investigations"][number];
    const runningTimeline = [
      ...base.timeline,
      { event: "decision", node: gateNode, attempt: 1, status: null, at: at(1000) },
      { event: "step_end", node: gateNode, attempt: 1, status: "ok", at: at(1000) },
      { event: "workaround_start", node: null, attempt: 1, status: null, at: at(1001) },
    ];
    const { router, queryClient } = renderRun({
      [RUN]: () => {
        if (stage === "paused") return base;
        if (stage === "running") {
          // Between the answer and the next pause the run is running: no open investigation.
          return {
            ...base,
            open_investigation: null,
            paused_step: null,
            timeline: runningTimeline,
            investigations: [answeredFirst],
          };
        }
        return {
          ...base,
          open_investigation: 2,
          timeline: [
            ...runningTimeline,
            { event: "workaround_end", node: null, attempt: 1, status: "failed", at: at(1050) },
            {
              event: "investigation",
              node: "order-processed",
              attempt: 2,
              status: null,
              at: at(1051),
            },
            { event: "gate", node: gateNode, attempt: 2, status: null, at: at(1051) },
          ],
          investigations: [
            answeredFirst,
            { ...base.investigations[0], number: 2 } as ScenarioRunDetail["investigations"][number],
          ],
          // The new proposal reuses the ids: o1 is the option that just failed.
          proposal: { proposal: 3, investigation: 2, options: base.proposal?.options ?? [] },
        };
      },
      [`POST ${RUN}/answer`]: () => {
        stage = "running";
        return {
          run_id: SCENARIO_RUN,
          project: "demo",
          investigation: 1,
          step: "order-processed",
          choice: "pick",
          option: "o1",
        };
      },
    });
    const options = await screen.findByRole("radiogroup", { name: "Options from the agent" });
    await user.click(within(options).getByRole("radio", { name: /o1 ·/ }));
    await user.click(screen.getByRole("button", { name: "Pick option o1" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Pick option o1" }),
    );
    await screen.findByText("Answer recorded: option o1 picked.");
    await waitFor(() => {
      expect(screen.queryByRole("radiogroup", { name: "Options from the agent" })).toBeNull();
    });

    // A pick on the reopened investigation's first paint, before the router lands the cleared
    // URL: the pick holds (review round 6, N1-R6b).
    let picked = false;
    const observer = new MutationObserver(() => {
      if (picked || screen.queryByText("proposal 3") === null) return;
      const group = screen.queryByRole("radiogroup", { name: "Options from the agent" });
      if (group === null) return;
      picked = true;
      within(group).getByRole("radio", { name: /o2 ·/ }).click();
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true });
    stage = "reopened";
    await act(async () => {
      await queryClient.invalidateQueries();
    });
    expect(await screen.findByText("proposal 3")).toBeInTheDocument();
    observer.disconnect();

    expect(picked).toBe(true);
    await waitFor(() => {
      expect(router.state.location.search).toBe("?option=o2");
    });
    await waitFor(() => {
      const reopened = screen.getByRole("radiogroup", { name: "Options from the agent" });
      expect(within(reopened).getByRole("radio", { name: /o2 ·/ })).toBeChecked();
    });
    expect(screen.getByRole("button", { name: "Pick option o2" })).toBeEnabled();
  });
});

/* Debugging a scenario run written as blocks (ADR 0049, spec 23): its pinned blocks with
 * their breakpoints, Step and Continue in a debug pause, and the values while paused. */
describe("ScenarioRunScreen (scenarios run debugging)", () => {
  const debugRoutes: ApiRoutes = {
    [RUN]: aDebugScenarioRun(),
    "/api/v1/approvals": aPage([]),
    [`${RUN}/values`]: aScenarioRunValues(),
  };

  it("scenarios run shows inputs, captures and outputs while paused", async () => {
    const user = userEvent.setup();
    const { requests } = renderRun(debugRoutes);

    const values = await screen.findByRole("complementary", { name: "Values while paused" });
    expect(await within(values).findByText("shop_order_id")).toBeInTheDocument();
    expect(values).toHaveTextContent("shop_order_id = T-1");
    // Environment values are inputs too.
    expect(values).toHaveTextContent("personal_name = dana-demo");
    const facts = screen.getByRole("complementary", { name: "Scenario run facts" });
    expect(facts).toHaveTextContent("order_id = 81234");
    // Each finished block, its values folded until opened.
    const finished = within(values).getByRole("list", { name: "Finished blocks" });
    const items = within(finished).getAllByRole("listitem");
    expect(items.map((item) => item.querySelector("summary")?.textContent)).toEqual([
      "1.1 queue-send · fetch-order--1 · Done",
      "1.2 order-state · fetch-order--2 · Done · 3 polls",
    ]);
    const held = items[1]?.querySelector("details");
    expect(held).not.toHaveAttribute("open");
    await user.click(within(finished).getByText(/1\.2 order-state/));
    expect(held).toHaveAttribute("open");
    const shown = within(held as HTMLElement);
    expect(shown.getByRole("group", { name: "With" })).toHaveTextContent(
      '{ "shop_order_id": "T-1" }',
    );
    expect(shown.getByRole("group", { name: "Output" })).toHaveTextContent(
      '{ "order_status": "ON_HOLD", "order_id": "81234" }',
    );
    expect(shown.getByRole("group", { name: "Last poll (3 polls)" })).toHaveTextContent(
      '"order_status": "ON_HOLD"',
    );
    expect(requests.filter((request) => request.url.endsWith("/values"))).toHaveLength(1);
  });

  it("scenarios run toggles a breakpoint; Step and Continue only in a debug pause", async () => {
    const user = userEvent.setup();
    // Running, not paused: the breakpoints, no Step or Continue, and no values read.
    const runningView = renderRun({ ...debugRoutes, [RUN]: aDebugScenarioRun({ debug: null }) });
    const runningBlocks = await screen.findByRole("region", { name: "Blocks" });
    // Offered once the hub says the run's environment is not production.
    expect(
      await within(runningBlocks).findByRole("button", { name: "Breakpoint before block 2.1" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "Step" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Continue" })).toBeNull();
    expect(runningView.requests.some((request) => request.url.endsWith("/values"))).toBe(false);
    runningView.unmount();

    // On a production environment: no breakpoint to set, no Step or Continue.
    const live = renderRun({ ...debugRoutes, [RUN]: aDebugScenarioRun({ environment: "live" }) });
    const liveBar = await screen.findByRole("region", { name: "Paused before block 2.1" });
    await waitFor(() => {
      expect(liveBar).toHaveTextContent(
        "Step and Continue are off: live is a production environment.",
      );
    });
    expect(within(liveBar).getByText(`./hub workflow run --resume ${SCENARIO_RUN}`)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Step" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Breakpoint before/ })).toBeNull();
    expect(screen.getByRole("region", { name: "Blocks" })).toHaveTextContent(
      "Breakpoints are off: live is a production environment.",
    );
    expect(live.requests.some((request) => request.url.endsWith("/values"))).toBe(false);
    live.unmount();

    // In a debug pause: toggle a breakpoint (by the keyboard), then Step.
    const written = [
      ["2.1", "2.2"],
      ["1.2", "2.1", "2.2"],
    ];
    let puts = 0;
    const { requests } = renderRun({
      ...debugRoutes,
      [`PUT ${RUN}/breakpoints`]: () => ({ run_id: SCENARIO_RUN, blocks: written[puts++] }),
      [`POST ${RUN}/step`]: { run_id: SCENARIO_RUN, project: "demo", action: "step" },
    });
    const blocks = await screen.findByRole("region", { name: "Blocks" });
    const next = await within(blocks).findByRole("button", { name: "Breakpoint before block 2.2" });
    const rows = within(blocks).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      "1Stage: Fetch orderBreakpoint",
      "1.1Do: queue-sendDoneBreakpoint",
      "1.2Wait until: order-stateDoneBreakpoint",
      "2Stage: ReviewBreakpoint",
      "2.1Do: queue-sendPaused before itBreakpoint",
      "2.2You: Check the review, then approve.Not startedBreakpoint",
    ]);
    expect(next).toHaveAttribute("aria-pressed", "false");
    next.focus();
    await user.keyboard(" ");
    await waitFor(() => {
      expect(next).toHaveAttribute("aria-pressed", "true");
    });
    const put = requests.find((request) => request.method === "PUT");
    expect(await put?.clone().json()).toEqual({ blocks: ["2.1", "2.2"] });
    // An earlier block goes in its place in the pinned tree's order, not at the end.
    const earlier = within(blocks).getByRole("button", { name: "Breakpoint before block 1.2" });
    await user.click(earlier);
    await waitFor(() => {
      expect(earlier).toHaveAttribute("aria-pressed", "true");
    });
    const second = requests.filter((request) => request.method === "PUT")[1];
    expect(await second?.clone().json()).toEqual({ blocks: ["1.2", "2.1", "2.2"] });

    const bar = screen.getByRole("region", { name: "Paused before block 2.1" });
    expect(bar).toHaveTextContent("Paused before block 2.1 (Do: queue-send), at its breakpoint.");
    expect(bar).toHaveTextContent(
      "Step runs the next block and pauses before the one after it; Continue runs to the next breakpoint or the end.",
    );
    await user.click(within(bar).getByRole("button", { name: "Step" }));
    expect(
      await within(bar).findByText(
        "Step sent: the scenario run goes on, and its events update this page.",
      ),
    ).toBeInTheDocument();
    // Both stay off until the run leaves the pause; the pressed one keeps focus (aria-disabled).
    const continueButton = within(bar).getByRole("button", { name: "Continue" });
    expect(continueButton).toHaveAttribute("aria-disabled", "true");
    expect(within(bar).getByRole("button", { name: "Step" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await user.click(continueButton);
    await user.click(within(bar).getByRole("button", { name: "Step" }));
    const step = requests.filter(
      (request) => request.method === "POST" && request.url.endsWith("/step"),
    );
    expect(step).toHaveLength(1);
    expect(requests.some((request) => request.url.endsWith("/continue"))).toBe(false);
  });

  it("scenarios run continues on the pinned tree after an edit", async () => {
    const user = userEvent.setup();
    // The builder removed the stage Review since the run started: the file holds 1 and 1.1.
    const edited = aScenarioDetail({
      version: 2,
      blocks: [
        { address: "1", kind: "stage", label: "Fetch order", entry_nodes: ["fetch-order--1"] },
        { address: "1.1", kind: "do", label: "queue-send", entry_nodes: ["fetch-order--1"] },
      ],
    });
    const { requests } = renderRun({
      ...debugRoutes,
      "/api/v1/scenarios/demo/order-lifecycle": edited,
      [`PUT ${RUN}/breakpoints`]: { run_id: SCENARIO_RUN, blocks: ["2.1", "2.2"] },
      [`POST ${RUN}/continue`]: { run_id: SCENARIO_RUN, project: "demo", action: "continue" },
    });

    const blocks = await screen.findByRole("region", { name: "Blocks" });
    expect(blocks).toHaveTextContent(
      "As this scenario run pinned them when it started: editing the scenario changes none of them.",
    );
    await user.click(
      await within(blocks).findByRole("button", { name: "Breakpoint before block 2.2" }),
    );
    const put = requests.find((request) => request.method === "PUT");
    expect(await put?.clone().json()).toEqual({ blocks: ["2.1", "2.2"] });
    const bar = screen.getByRole("region", { name: "Paused before block 2.1" });
    await user.click(within(bar).getByRole("button", { name: "Continue" }));
    expect(
      await within(bar).findByText(
        "Continue sent: the scenario run goes on, and its events update this page.",
      ),
    ).toBeInTheDocument();
    expect(
      requests.filter((request) => request.method === "POST" && request.url.endsWith("/continue")),
    ).toHaveLength(1);
  });

  it("scenarios run offers no Step, Continue or breakpoint while its environment is unknown", async () => {
    // The scenario still reads: the hub has not said yet whether the environment is production.
    const { requests } = renderRun({
      ...debugRoutes,
      "/api/v1/scenarios/demo/order-lifecycle": "pending",
    });

    const bar = await screen.findByRole("region", { name: "Paused before block 2.1" });
    expect(bar).toHaveTextContent("Nothing of this block has run yet.");
    await screen.findByRole("region", { name: "Blocks" });
    expect(within(bar).queryByRole("button", { name: "Step" })).toBeNull();
    expect(within(bar).queryByRole("button", { name: "Continue" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Breakpoint before/ })).toBeNull();
    expect(requests.some((request) => request.url.endsWith("/values"))).toBe(false);
  });

  it("scenarios run still offers Continue when the edited scenario no longer reads", async () => {
    // An edit left the file broken: the server's production refusal still stands (409).
    renderRun({
      ...debugRoutes,
      "/api/v1/scenarios/demo/order-lifecycle": aProblem({
        status: 422,
        title: "Invalid scenario",
      }),
    });

    const bar = await screen.findByRole("region", { name: "Paused before block 2.1" });
    expect(await within(bar).findByRole("button", { name: "Continue" })).not.toHaveAttribute(
      "aria-disabled",
    );
    expect(screen.getByRole("button", { name: "Breakpoint before block 2.2" })).toBeInTheDocument();
  });

  it("scenarios run clears a refused Step once the run pauses again", async () => {
    const user = userEvent.setup();
    let moved = false;
    const { queryClient } = renderRun({
      ...debugRoutes,
      [RUN]: () =>
        aDebugScenarioRun(
          moved
            ? {
                debug: { block: "2.2", node: "review--2", reason: "step", number: 2, at: at(60) },
                stepping: true,
              }
            : {},
        ),
      [`POST ${RUN}/step`]: aProblem({
        status: 409,
        title: "Conflict",
        detail: "Another debug command of this scenario run is still running.",
      }),
    });

    const bar = await screen.findByRole("region", { name: "Paused before block 2.1" });
    await user.click(await within(bar).findByRole("button", { name: "Step" }));
    expect(await within(bar).findByRole("alert")).toHaveTextContent(
      "Could not send StepAnother debug command of this scenario run is still running.",
    );
    // The run paused again (the other command ran): the refusal was about the pause before.
    moved = true;
    await act(async () => {
      await queryClient.invalidateQueries();
    });
    const next = await screen.findByRole("region", { name: "Paused before block 2.2" });
    expect(next).toHaveTextContent("after a Step.");
    expect(within(next).queryByRole("alert")).toBeNull();
    expect(within(next).getByRole("button", { name: "Step" })).not.toHaveAttribute("aria-disabled");
  });

  it("scenarios run puts focus on its heading when the debug pause it was in ends", async () => {
    const user = userEvent.setup();
    let stepped = false;
    renderRun({
      ...debugRoutes,
      [RUN]: () => aDebugScenarioRun(stepped ? { debug: null } : {}),
      [`POST ${RUN}/step`]: () => {
        stepped = true;
        return { run_id: SCENARIO_RUN, project: "demo", action: "step" };
      },
    });

    const bar = await screen.findByRole("region", { name: "Paused before block 2.1" });
    const step = await within(bar).findByRole("button", { name: "Step" });
    step.focus();
    await user.keyboard("{Enter}");
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Paused before block 2.1" })).toBeNull();
    });
    expect(screen.getByRole("heading", { level: 1 })).toHaveFocus();
  });

  it("scenarios run sets no breakpoint once it ended done or cancelled", async () => {
    // A failed scenario run can be resumed: its toggles stay.
    const failed = renderRun({
      ...debugRoutes,
      [RUN]: aDebugScenarioRun({ status: "failed", debug: null }),
    });
    expect(
      await screen.findByRole("button", { name: "Breakpoint before block 2.1" }),
    ).toBeInTheDocument();
    failed.unmount();

    for (const status of ["done", "cancelled"] as const) {
      const view = renderRun({ ...debugRoutes, [RUN]: aDebugScenarioRun({ status, debug: null }) });
      const blocks = await screen.findByRole("region", { name: "Blocks" });
      await waitFor(() => {
        expect(view.queryClient.isFetching()).toBe(0);
      });
      expect(within(blocks).queryByRole("button", { name: /^Breakpoint before/ })).toBeNull();
      expect(blocks).not.toHaveTextContent("A breakpoint pauses the scenario run");
      view.unmount();
    }
  });

  it("scenarios run shows a graph run's values by node id while an investigation waits", async () => {
    // The default run: a graph run (no blocks) paused at an investigation.
    const user = userEvent.setup();
    const { requests } = renderRun();

    const values = await screen.findByRole("complementary", { name: "Values while paused" });
    const finished = await within(values).findByRole("list", { name: "Finished blocks" });
    expect(within(finished).getByText("order-processed · Failed · 2 polls")).toBeInTheDocument();
    await user.click(within(finished).getByText("order-processed · Failed · 2 polls"));
    expect(within(finished).getByRole("group", { name: "Last poll (2 polls)" })).toHaveTextContent(
      '{ "status": "OPEN" }',
    );
    expect(screen.queryByRole("region", { name: "Blocks" })).toBeNull();
    expect(requests.filter((request) => request.url.endsWith("/values"))).toHaveLength(1);
  });

  it("scenarios run reads its values again once another block ended in the same pause", async () => {
    // A Together: one path waits at an ask while another goes on and ends a block.
    let ended = false;
    const askRun = () =>
      aDebugScenarioRun({
        debug: null,
        timeline: [
          ...aDebugScenarioRun().timeline,
          ...(ended
            ? [
                {
                  event: "step_end",
                  node: "review--1",
                  attempt: 1,
                  status: "ok",
                  at: at(70),
                  block: "2.1",
                },
              ]
            : []),
        ],
      });
    const { requests, queryClient } = renderRun({
      ...debugRoutes,
      [RUN]: askRun,
      "/api/v1/approvals": aPage([gate(`${SCENARIO_RUN}:review--2__ask:1`, "policy")]),
    });

    await screen.findByRole("list", { name: "Finished blocks" });
    expect(requests.filter((request) => request.url.endsWith("/values"))).toHaveLength(1);
    ended = true;
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ["api", "/api/v1/scenario-runs/{run_id}"] });
    });
    await waitFor(() => {
      expect(requests.filter((request) => request.url.endsWith("/values"))).toHaveLength(2);
    });
  });

  it("scenarios run says its values wait for a pause the server counts", async () => {
    renderRun({
      ...debugRoutes,
      [`${RUN}/values`]: aProblem({ status: 409, title: "Conflict", code: "not_paused" }),
    });

    const values = await screen.findByRole("complementary", { name: "Values while paused" });
    expect(
      await within(values).findByText(
        "The scenario run is not paused right now: its values show while it is paused.",
      ),
    ).toBeInTheDocument();
  });

  it("scenarios run shows a credential mark in a finished block's values as a chip", async () => {
    const user = userEvent.setup();
    renderRun({
      ...debugRoutes,
      [`${RUN}/values`]: aScenarioRunValues({
        blocks: [
          {
            address: "1.1",
            node: "fetch-order--1",
            attempt: 1,
            status: "ok",
            with: { token: "Bearer <credential SHOP_TOKEN>" },
            output: { echoed: "<credential SHOP_TOKEN>" },
            polls: 0,
            last_poll: null,
          },
        ],
      }),
    });

    const finished = await screen.findByRole("list", { name: "Finished blocks" });
    await user.click(within(finished).getByText(/1\.1 queue-send/));
    const withValues = within(finished).getByRole("group", { name: "With" });
    expect(
      within(withValues).getByRole("note", { name: "Redacted credential SHOP_TOKEN" }),
    ).toBeInTheDocument();
    expect(withValues).toHaveTextContent(/"token": "Bearer \[redacted: credential SHOP_TOKEN\]/);
    expect(withValues).not.toHaveTextContent("<credential");
    expect(
      within(within(finished).getByRole("group", { name: "Output" })).getByRole("note", {
        name: "Redacted credential SHOP_TOKEN",
      }),
    ).toBeInTheDocument();
  });

  it("scenarios run in a debug pause has no serious a11y violation (a11y)", async () => {
    const { container } = renderRun(debugRoutes);
    await screen.findByRole("region", { name: "Paused before block 2.1" });
    await screen.findByRole("list", { name: "Finished blocks" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
