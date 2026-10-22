import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

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
  aScenarioDetail,
  aScenarioRunDetail,
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

  it("scenarios run after an answer: a toast, a resuming line, focus on the heading", async () => {
    const user = userEvent.setup();
    let answered = false;
    renderRun({
      [RUN]: () =>
        answered
          ? aScenarioRunDetail({
              open_investigation: null,
              paused_step: null,
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
                  closed: false,
                },
              ],
            })
          : aScenarioRunDetail(),
      [`POST ${RUN}/answer`]: () => {
        answered = true;
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
    expect(document.querySelector("[data-announcer]")).toHaveTextContent(
      "Scenario run paused at order-processed",
    );
    await user.click(within(options).getByRole("radio", { name: /o2/ }));
    await user.click(screen.getByRole("button", { name: "Pick option o2" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Pick option o2" }),
    );

    expect(await screen.findByText("Answer recorded: option o2 picked.")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Paused at order-processed" })).toBeNull();
    });
    expect(
      screen.getByText(
        "Answer recorded: option o2 picked. The scenario run resumes; its events update this page.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveFocus();
    expect(document.querySelector("[data-announcer]")).toHaveTextContent("Answer recorded");
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
    expect(draftRow?.querySelector("td")).toHaveAttribute("colspan", "4");
    expect(table).toHaveClass("sc-plan");
  });
});
