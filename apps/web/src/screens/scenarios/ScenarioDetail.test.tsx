import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aDraftRow,
  anApproval,
  aPage,
  aProblem,
  aDebugScenarioRun,
  aRun,
  aScenarioAction,
  aScenarioDetail,
  aScenarioRunDetail,
  aScenarioPlan,
  aScenarioPlanRow,
  aScenarioRunRef,
  aTreeDocument,
  at,
  renderWithApi,
  SCENARIO_RUN,
  type ApiRoutes,
} from "../../testing/builders";
import { DiscussProvider, useDiscuss } from "../../shell/discuss";
import { ScenarioDetailScreen } from ".";
import { codeText } from "../../testing/text";

/** What the Discuss panel would be handed on this page. */
function BriefProbe() {
  const { target } = useDiscuss();
  return <output aria-label="discuss brief">{target?.brief ?? ""}</output>;
}

const PATH = "/scenarios/demo/order-lifecycle";
const DETAIL = "/api/v1/scenarios/demo/order-lifecycle";
const PLAN = `POST ${DETAIL}/plan`;
const START = `POST ${DETAIL}/runs`;
const VALIDATE = "POST /api/v1/projects/demo/scenarios/validate";
const WORKFLOW_RUN = `/api/v1/workflow-runs/${SCENARIO_RUN}`;
const SCENARIO_RUN_RECORD = `/api/v1/scenario-runs/${SCENARIO_RUN}`;
const COMMIT = aDraftRow().accept_command ?? "";

// The scenario written as a graph: three steps, the last one calling a draft action.
const GRAPH = {
  version: 1,
  kind: "scenario",
  name: "order-lifecycle",
  revision: 1,
  inputs: { external_ref: { type: "string", required: true } },
  nodes: [
    { id: "fetch-order", type: "action", action: "send-queue-message" },
    {
      id: "order-on-hold",
      type: "expect",
      action: "get-order-by-ref",
      depends_on: ["fetch-order"],
      every: "10s",
      timeout: "5m",
      until_when: "$self.output.status == 'ON_HOLD'",
    },
    {
      id: "render-pdf",
      type: "action",
      action: "render-invoice-pdf",
      depends_on: ["order-on-hold"],
    },
  ],
};

// The same scenario written as blocks: one stage of three blocks (1.1, 1.2, 1.3).
const TREE = {
  version: 2,
  kind: "scenario",
  name: "order-lifecycle",
  revision: 1,
  inputs: { external_ref: { required: true } },
  stages: [
    {
      name: "Fetch",
      steps: [
        { do: "send-queue-message" },
        {
          wait_until: "get-order-by-ref",
          until: "$self.output.status == 'ON_HOLD'",
          every: "10s",
          timeout: "5m",
        },
        { do: "render-invoice-pdf" },
      ],
    },
  ],
};

const BLOCKS = [
  { address: "1", kind: "stage", label: "Fetch", entry_nodes: ["fetch-order--1"] },
  { address: "1.1", kind: "do", label: "send-queue-message", entry_nodes: ["fetch-order--1"] },
  {
    address: "1.2",
    kind: "wait_until",
    label: "get-order-by-ref",
    entry_nodes: ["fetch-order--2"],
  },
  { address: "1.3", kind: "do", label: "render-invoice-pdf", entry_nodes: ["fetch-order--3"] },
];
const RUN_BLOCKS = BLOCKS.map(({ address, kind, label }) => ({ address, kind, label }));

/** A timeline line of a block of the tree above. */
function line(event: string, block: string, seconds: number, status: string | null = null) {
  const node = `fetch-order--${block.split(".")[1] ?? ""}`;
  return { event, node, attempt: 1, status, at: at(seconds), block };
}

const draftAction = aScenarioAction({
  ref: "render-invoice-pdf",
  name: "render-invoice-pdf",
  effect: "write",
  description: "Render the order's invoice PDF",
  draft: true,
  accept_command: COMMIT,
});

const actions = [
  aScenarioAction({ ref: "send-queue-message", name: "send-queue-message", effect: "write" }),
  aScenarioAction({
    ref: "get-order-by-ref",
    name: "get-order-by-ref",
    description: "Read one order by its ref",
  }),
  draftAction,
];

const library = {
  items: actions.map((action) => ({
    action,
    output_fields: action.name === "get-order-by-ref" ? [{ path: "status", type: "string" }] : [],
    used_by: ["order-lifecycle"],
  })),
  problems: [],
};

type DetailOverrides = Parameters<typeof aScenarioDetail>[0];

function graphDetail(overrides: DetailOverrides = {}) {
  return aScenarioDetail({ document: GRAPH, content_hash: "sha256:aaa", actions, ...overrides });
}

function treeDetail(overrides: DetailOverrides = {}) {
  return aScenarioDetail({
    document: TREE,
    content_hash: "sha256:aaa",
    version: 2,
    blocks: BLOCKS,
    actions,
    ...overrides,
  });
}

const denied = aScenarioPlan({
  denied: true,
  rows: [...aScenarioPlan().rows, aDraftRow()],
});

const routes: ApiRoutes = {
  [DETAIL]: graphDetail(),
  "/api/v1/approvals": aPage([]),
  "/api/v1/workflow-runs": aPage([]),
  "/api/v1/projects/demo/actions": library,
  [VALIDATE]: () => ({ loads: true, yaml: "version: 1\n", problems: [], nodes: [] }),
};

function renderDetail(extra: ApiRoutes = {}, path = PATH) {
  return renderWithApi(<ScenarioDetailScreen />, {
    routes: { ...routes, ...extra },
    path,
    route: "/scenarios/:project/:name",
  });
}

/** Picks the environment, then plans; external_ref has no value anywhere, so Plan asks for it. */
async function planIn(environment: string, ref = "T-1") {
  const user = userEvent.setup();
  const select = await screen.findByLabelText("Environment");
  if ((select as HTMLSelectElement).value !== environment) {
    await user.selectOptions(select, environment);
  }
  await screen.findByText("No problems");
  await user.click(screen.getByRole("button", { name: `Plan in ${environment}` }));
  const form = await screen.findByRole("form", { name: "Values to plan with" });
  await user.type(within(form).getByRole("textbox", { name: "external_ref" }), ref);
  await user.click(within(form).getByRole("button", { name: `Plan in ${environment}` }));
  return user;
}

function runBar() {
  return screen.getByRole("form", { name: "Run order-lifecycle" });
}

function verdictLine() {
  return within(runBar()).getByRole("status");
}

function runPanel() {
  return screen.getByRole("complementary", { name: "Scenario runs of order-lifecycle" });
}

function row(name: RegExp) {
  return screen.getByRole("treeitem", { name });
}

function startButton() {
  return within(runBar()).getByRole("button", { name: "Start scenario run" });
}

function startRequest(requests: Request[]) {
  return requests.find((request) => request.method === "POST" && request.url.endsWith("/runs"));
}

const aScenarioWorkflowRun = (overrides: Parameters<typeof aRun>[0] = {}) =>
  aRun({
    id: SCENARIO_RUN,
    kind: "scenario",
    workflow: "scenario:order-lifecycle",
    content_hash: "sha256:5f0c2e1d",
    revision: 1,
    status: "running",
    steps: [],
    ...overrides,
  });

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("ScenarioDetailScreen (scenarios detail)", () => {
  it("scenarios detail plans in a chosen environment and shows the verdict (deny; the draft's commit command once in Before you start)", async () => {
    const { requests } = renderDetail(
      { [PLAN]: aScenarioPlan({ ...denied, environment: "qa", access: "read" }) },
      `${PATH}?env=qa`,
    );

    await screen.findByRole("form", { name: "Run order-lifecycle" });
    expect(screen.getByLabelText("Environment")).toHaveValue("qa");
    // The plan never runs on load, even with ?env=.
    expect(requests.some((request) => request.url.endsWith("/plan"))).toBe(false);
    expect(verdictLine()).toHaveTextContent(
      "Plan the scenario to see what each step will do in qa. Nothing is changed by a plan.",
    );
    await planIn("qa");

    const link = await within(runBar()).findByRole("link", {
      name: "Cannot start: 1 draft action needs acceptance. See Before you start.",
    });
    expect(link).toHaveAttribute("href", "#before-you-start");
    const sent = requests.find((request) => request.url.endsWith("/plan"));
    expect(await sent?.clone().json()).toEqual({
      environment: "qa",
      inputs: { external_ref: "T-1" },
    });
    const plan = within(runPanel()).getByRole("region", { name: "This plan" });
    expect(within(plan).getByText("qa · access read", { selector: "b" })).toBeInTheDocument();
    expect(within(plan).getByText("3 steps: 1 read, 2 write")).toBeInTheDocument();
    // Each step's row says its plan; the draft is said once, in Before you start, not per row.
    expect(row(/^Step 1,/)).toHaveTextContent("Plan: Sends FETCH_ORDERS for T-1");
    const render = row(/^Step 3,/);
    expect(render).toHaveTextContent("Plan: runs with values known at run time");
    expect(within(render).queryByText("Draft action")).not.toBeInTheDocument();
    const before = within(runPanel()).getByRole("region", { name: "Before you start" });
    expect(before).toHaveTextContent(
      "1 draft action to commitYou can plan now. A scenario run starts once this action is committed in the hub checkout: one commit does it.",
    );
    // The commit command is written once on the page, in Before you start.
    expect(screen.getAllByText(codeText(COMMIT))).toHaveLength(1);
    // AC-596.5: and the page's text holds it once (no copy in a row, a title or the verdict).
    expect(document.body.textContent.split(COMMIT)).toHaveLength(2);
    expect(within(before).getByText(codeText(COMMIT))).toBeInTheDocument();
    expect(startButton()).toBeDisabled();
  });

  it("scenarios detail names the denied steps in the verdict and on Start", async () => {
    renderDetail({
      [PLAN]: aScenarioPlan({
        denied: true,
        rows: [
          aScenarioPlanRow({ decision: "deny", reason: "write is denied in personal" }),
          aScenarioPlanRow({ step: "order-on-hold", effect: "read" }),
        ],
      }),
    });
    await planIn("personal");

    expect(
      await within(runBar()).findByText("Cannot start: fetch-order is denied in personal."),
    ).toBeInTheDocument();
    expect(startButton()).toBeDisabled();
    expect(startButton()).toHaveAttribute(
      "title",
      "Cannot start: fetch-order is denied in personal.",
    );
  });

  it("scenarios detail names why a denied plan with no denied step cannot start", async () => {
    renderDetail({ [PLAN]: aScenarioPlan({ denied: true }) });
    await planIn("personal");

    expect(
      await within(runBar()).findByText(
        "Cannot start in personal: the plan does not allow a start there.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Cannot start: +is denied/)).toBeNull();
  });

  it("scenarios detail starts a scenario run after its confirm, stays and shows it", async () => {
    let started = false;
    const { requests, router } = renderDetail({
      [PLAN]: aScenarioPlan({
        rows: [
          ...aScenarioPlan().rows,
          aScenarioPlanRow({ step: "resolve-cover", decision: "ask" }),
        ],
      }),
      [START]: () => {
        started = true;
        return { run_id: SCENARIO_RUN, project: "demo", action: "start" };
      },
      [DETAIL]: () => graphDetail({ runs: started ? [aScenarioRunRef()] : [] }),
      [WORKFLOW_RUN]: aScenarioWorkflowRun(),
      [SCENARIO_RUN_RECORD]: aScenarioRunDetail({ polls: [] }),
    });
    const user = await planIn("personal");

    expect(
      await within(runBar()).findByText(
        "Can start in personal · 3 steps: 1 read, 2 write · 1 asks you",
      ),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Regression" }));
    await user.click(startButton());
    const dialog = screen.getByRole("alertdialog", { name: "Start a scenario run in personal?" });
    expect(dialog).toHaveTextContent(
      "It runs 3 steps in personal: 1 read and 2 write. resolve-cover asks you before it runs. Regression mode: the first step that does not reach its expected state fails the scenario run.",
    );
    expect(within(dialog).getByRole("button", { name: "Back to plan" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Start scenario run" }));

    // Once listed, the dialog closes, the page stays and shows the new scenario run.
    const runs = within(runPanel()).getByRole("region", { name: "Scenario runs" });
    expect(
      await within(runs).findByRole(
        "link",
        { name: `Open scenario run ${SCENARIO_RUN}` },
        { timeout: 5000 },
      ),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(router.state.location.pathname).toBe(PATH);
    expect(new URLSearchParams(router.state.location.search).get("run")).toBe(SCENARIO_RUN);
    expect(within(runs).getByRole("button", { name: "Shown" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      await screen.findByRole("region", { name: `Scenario run ${SCENARIO_RUN}` }),
    ).toBeInTheDocument();
    expect(await startRequest(requests)?.clone().json()).toEqual({
      environment: "personal",
      inputs: { external_ref: "T-1" },
      mode: "regression",
    });
  });

  it("scenarios detail refuses a start with the server's reason", async () => {
    renderDetail({
      [PLAN]: aScenarioPlan(),
      [START]: aProblem({
        status: 409,
        title: "Workflow run command refused",
        detail: "step fetch-order: deny (access read in qa does not allow write)",
      }),
    });
    const user = await planIn("personal");
    await within(runBar()).findByText(/^Can start in personal/);
    await user.click(startButton());
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Start scenario run" }),
    );

    const alert = await screen.findByText("Could not start the scenario run");
    expect(alert.closest("[role=alert]")).toHaveTextContent(
      "step fetch-order: deny (access read in qa does not allow write)Nothing was started.",
    );
  });

  it("scenarios detail never sends a second start, even after the scenario run is late", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { requests } = renderDetail({
      [PLAN]: aScenarioPlan(),
      [START]: { run_id: SCENARIO_RUN, project: "demo", action: "start" },
    });
    const user = await planIn("personal");
    await within(runBar()).findByText(/^Can start in personal/);
    await user.click(startButton());
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Start scenario run" }),
    );
    await screen.findByText("Started. Waiting for the scenario run's first event…");

    act(() => {
      vi.advanceTimersByTime(31_000);
    });

    const dialog = await screen.findByRole("dialog", { name: "Start a scenario run in personal?" });
    expect(within(dialog).getByText(/has not reported in 30 s/)).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(
      screen
        .queryAllByRole("button", { name: "Start scenario run" })
        .filter((button) => !(button as HTMLButtonElement).disabled),
    ).toHaveLength(0);
    expect(
      within(dialog).getByRole("link", { name: `Open scenario run ${SCENARIO_RUN} anyway` }),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Back to plan" }));
    expect(startButton()).toBeDisabled();
    const starts = requests.filter((r) => r.method === "POST" && r.url.endsWith("/runs"));
    expect(starts).toHaveLength(1);
  });

  it("scenarios detail shows the production banner once a production environment is picked", async () => {
    const user = userEvent.setup();
    const reason = "live is a production environment: writes and destroys are denied";
    renderDetail({
      [PLAN]: aScenarioPlan({
        environment: "live",
        access: "read",
        production: true,
        denied: true,
        rows: [
          aScenarioPlanRow({ decision: "deny", reason_kind: "production", reason }),
          aScenarioPlanRow({
            step: "resolve-cover",
            decision: "deny",
            reason_kind: "production",
            reason,
          }),
        ],
      }),
    });
    const banner =
      "live is a production environment: writes and destroys are denied there, and breakpoints are off.";

    await user.selectOptions(await screen.findByLabelText("Environment"), "live");
    expect(screen.getByText(banner)).toBeInTheDocument();
    await planIn("live");

    expect(
      await within(runBar()).findByText(
        "Cannot start: fetch-order and resolve-cover are denied in live.",
      ),
    ).toBeInTheDocument();
    expect(
      within(within(runPanel()).getByRole("region", { name: "This plan" })).getByText(
        "live · production · access read",
      ),
    ).toBeInTheDocument();
  });

  it("scenarios detail never opens on a production environment, even the last one used", async () => {
    window.localStorage.setItem("ah.scenarios.env.demo", JSON.stringify(["live"]));
    renderDetail({
      [DETAIL]: graphDetail({
        environments: [
          { name: "live", access: "read", production: true },
          { name: "qa", access: "read", production: false },
          { name: "personal", access: "write", production: false },
        ],
      }),
    });

    expect(await screen.findByLabelText("Environment")).toHaveValue("qa");
    expect(screen.queryByText(/is a production environment/)).toBeNull();
  });

  it("scenarios detail opens on the last environment used when it is not production", async () => {
    window.localStorage.setItem("ah.scenarios.env.demo", JSON.stringify(["qa"]));
    renderDetail();

    expect(await screen.findByLabelText("Environment")).toHaveValue("qa");
  });

  it("scenarios detail lands an old Run mode link on the one screen", async () => {
    const { router } = renderDetail({}, `${PATH}?mode=run&view=document&env=qa`);

    expect(await screen.findByRole("form", { name: "Run order-lifecycle" })).toBeInTheDocument();
    await waitFor(() => {
      expect(router.state.location.search).toBe("?env=qa");
    });
    expect(screen.getByLabelText("Environment")).toHaveValue("qa");
    expect(row(/^Step 1,/)).toBeInTheDocument();
  });

  it("scenarios detail follows a running scenario run: the strip with Cancel and each step's state", async () => {
    const step = (key: string, status: "ok" | "running") => ({
      attempt: 1,
      ended_at: status === "ok" ? "2026-10-23T10:01:00Z" : null,
      key,
      max_attempts: 1,
      reason: null,
      session_ids: [],
      started_at: "2026-10-23T10:00:00Z",
      status,
    });
    renderDetail({
      [DETAIL]: graphDetail({ runs: [aScenarioRunRef({ status: "running" })] }),
      [WORKFLOW_RUN]: aScenarioWorkflowRun({
        steps: [step("fetch-order", "ok"), step("order-on-hold", "running")],
      }),
      [SCENARIO_RUN_RECORD]: aScenarioRunDetail({
        polls: [1, 2, 3].map((poll) => ({
          node: "order-on-hold",
          attempt: 1,
          poll,
          held: false,
          at: null,
        })),
      }),
    });

    const strip = await screen.findByRole("region", { name: `Scenario run ${SCENARIO_RUN}` });
    expect(within(strip).getByRole("status")).toHaveTextContent(
      /is running in personal · Interactive · at step order-on-hold/,
    );
    expect(within(strip).getByRole("link", { name: /Open scenario run/ })).toHaveAttribute(
      "href",
      `${PATH}/runs/${SCENARIO_RUN}`,
    );
    expect(within(strip).getByRole("button", { name: /Cancel scenario run/ })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Follow" })).toBeChecked();
    expect(row(/^Step 1,/)).toHaveTextContent("Done");
    await waitFor(() => {
      expect(row(/^Step 2,/)).toHaveTextContent(/Running · check 3/);
    });
    expect(row(/^Step 2,/)).toHaveAttribute("aria-current", "step");
    expect(row(/^Step 3,/)).toHaveTextContent("Not started");
    // While it runs, a new start waits.
    expect(startButton()).toBeDisabled();
  });

  it("scenarios detail follows a scenario run written as blocks: each block's state and what it kept", async () => {
    renderDetail({
      [DETAIL]: treeDetail({ runs: [aScenarioRunRef({ status: "running" })] }),
      [WORKFLOW_RUN]: aScenarioWorkflowRun(),
      [SCENARIO_RUN_RECORD]: aDebugScenarioRun({
        debug: null,
        breakpoints: [],
        timeline: [
          { event: "start", node: null, attempt: null, status: null, at: at(0), block: null },
          line("step_start", "1.1", 5),
          line("step_end", "1.1", 10, "ok"),
          line("step_start", "1.2", 11),
        ],
        polls: [1, 2, 3].map((poll) => ({
          node: "fetch-order--2",
          attempt: 1,
          poll,
          held: false,
          at: at(11 + poll),
        })),
        captures: [{ node: "fetch-order--1", attempt: 1, name: "order_id", value: "81234" }],
        blocks: RUN_BLOCKS,
      }),
    });

    const strip = await screen.findByRole("region", { name: `Scenario run ${SCENARIO_RUN}` });
    await waitFor(() => {
      expect(within(strip).getByRole("status")).toHaveTextContent(/at block 1\.2/);
    });
    expect(row(/^Step 1\.1,/)).toHaveTextContent("Done");
    expect(row(/^Step 1\.1,/)).toHaveTextContent("Kept order_id = 81234");
    expect(row(/^Step 1\.2,/)).toHaveTextContent(/Running · check 3/);
    expect(row(/^Step 1\.3,/)).toHaveTextContent("Not started");
  });

  it("scenarios detail shows a debug pause in the run panel and on the block it holds", async () => {
    renderDetail({
      [DETAIL]: treeDetail({ runs: [aScenarioRunRef({ status: "running" })] }),
      [WORKFLOW_RUN]: aScenarioWorkflowRun(),
      [SCENARIO_RUN_RECORD]: aDebugScenarioRun({
        debug: {
          block: "1.2",
          node: "fetch-order--2",
          reason: "breakpoint",
          number: 1,
          at: at(41),
        },
        breakpoints: ["1.2"],
        timeline: [
          { event: "start", node: null, attempt: null, status: null, at: at(0), block: null },
          line("step_start", "1.1", 5),
          line("step_end", "1.1", 10, "ok"),
        ],
        blocks: RUN_BLOCKS,
      }),
    });

    const strip = await screen.findByRole("region", { name: `Scenario run ${SCENARIO_RUN}` });
    await waitFor(() => {
      expect(within(strip).getByRole("status")).toHaveTextContent(
        /is paused before block 1\.2 at its breakpoint in personal/,
      );
    });
    expect(
      within(runPanel()).getByRole("region", { name: "Paused before block 1.2" }),
    ).toHaveTextContent(
      "Paused before block 1.2 (Wait until: get-order-by-ref), at its breakpoint.",
    );
    expect(within(row(/^Step 1\.2,/)).getByText("Paused before it")).toBeInTheDocument();
    expect(within(row(/^Step 1\.1,/)).queryByText("Paused before it")).toBeNull();
    // The live run's own breakpoint shows on its block.
    expect(
      within(row(/^Step 1\.2,/)).getByRole("button", { name: "Breakpoint before block 1.2 (b)" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("scenarios detail sets breakpoints on a scenario written as blocks and starts with them", async () => {
    const { requests } = renderDetail({
      [DETAIL]: treeDetail(),
      [PLAN]: aScenarioPlan(),
      [START]: { run_id: SCENARIO_RUN, project: "demo", action: "start" },
    });
    const user = userEvent.setup();

    const toggle = await screen.findByRole("button", { name: "Breakpoint before block 1.2 (b)" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");

    // A production environment takes no breakpoint: none is offered there.
    await user.selectOptions(screen.getByLabelText("Environment"), "live");
    expect(screen.queryByRole("button", { name: /^Breakpoint before/ })).toBeNull();
    await user.selectOptions(screen.getByLabelText("Environment"), "personal");
    expect(screen.getByRole("button", { name: "Breakpoint before block 1.2 (b)" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await planIn("personal");
    await within(runBar()).findByText(/^Can start in personal/);
    await user.click(startButton());
    const dialog = screen.getByRole("alertdialog", { name: "Start a scenario run in personal?" });
    expect(dialog).toHaveTextContent("It pauses before block 1.2, its breakpoint.");
    await user.click(within(dialog).getByRole("button", { name: "Start scenario run" }));
    await waitFor(() => {
      expect(startRequest(requests)).toBeDefined();
    });
    expect(await startRequest(requests)?.clone().json()).toEqual({
      environment: "personal",
      inputs: { external_ref: "T-1" },
      mode: "interactive",
      breakpoints: ["1.2"],
    });
  });

  it("scenarios detail shows and hides a past scenario run on the steps with ?run=", async () => {
    const user = userEvent.setup();
    const { router } = renderDetail({
      [DETAIL]: graphDetail({
        runs: [aScenarioRunRef({ status: "done", ended_at: at(60) })],
      }),
      [WORKFLOW_RUN]: aScenarioWorkflowRun({
        status: "done",
        steps: [
          {
            attempt: 1,
            ended_at: at(30),
            key: "fetch-order",
            max_attempts: 1,
            reason: null,
            session_ids: [],
            started_at: at(5),
            status: "ok",
          },
        ],
      }),
      [SCENARIO_RUN_RECORD]: aScenarioRunDetail(),
    });

    const runs = await screen.findByRole("region", { name: "Scenario runs" });
    expect(
      within(runs).getByRole("link", { name: `Open scenario run ${SCENARIO_RUN}` }),
    ).toHaveAttribute("href", `${PATH}/runs/${SCENARIO_RUN}`);
    expect(within(runs).getByText("personal")).toBeInTheDocument();
    // A finished scenario run is not shown until picked.
    expect(screen.queryByRole("region", { name: `Scenario run ${SCENARIO_RUN}` })).toBeNull();

    await user.click(within(runs).getByRole("button", { name: "Show" }));
    expect(new URLSearchParams(router.state.location.search).get("run")).toBe(SCENARIO_RUN);
    const strip = await screen.findByRole("region", { name: `Scenario run ${SCENARIO_RUN}` });
    expect(within(strip).getByRole("status")).toHaveTextContent(/· Done in personal/);
    await waitFor(() => {
      expect(row(/^Step 1,/)).toHaveTextContent("Last run:");
    });
    expect(within(runs).getByRole("button", { name: "Shown" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(within(strip).getByRole("button", { name: "Hide its states" }));
    expect(new URLSearchParams(router.state.location.search).has("run")).toBe(false);
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: `Scenario run ${SCENARIO_RUN}` })).toBeNull();
    });
    expect(within(runs).getByRole("button", { name: "Show" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("scenarios detail hands Discuss the brief of the scenario's own format", async () => {
    const tree = aScenarioDetail({ document: aTreeDocument("blocks-together"), version: 2 });
    renderWithApi(
      <DiscussProvider>
        <ScenarioDetailScreen />
        <BriefProbe />
      </DiscussProvider>,
      {
        routes: { ...routes, [DETAIL]: tree },
        path: PATH,
        route: "/scenarios/:project/:name",
      },
    );

    const brief = await screen.findByLabelText("discuss brief");
    await waitFor(() => {
      expect(brief).toHaveTextContent("This scenario is written as blocks: `version: 2`");
    });
    expect(brief).not.toHaveTextContent("schema v1");
    expect(brief).not.toHaveTextContent("`nodes`");
  });

  describe("run bar", () => {
    it("scenarios detail lists the declared environments with their access and locks them while planning", async () => {
      // AC-596.2.2: each environment as name · [production · ]access, its access in words.
      renderDetail({ [PLAN]: "pending" });
      const select = await screen.findByLabelText("Environment");
      expect(
        within(select)
          .getAllByRole("option")
          .map((option) => option.textContent),
      ).toEqual(["personal · access write", "qa · access read", "live · production · access read"]);
      expect(select).toHaveAttribute("title", "Agents may change data here.");
      await userEvent.setup().selectOptions(select, "qa");
      expect(select).toHaveAttribute("title", "Agents only read here.");

      await planIn("qa");
      await waitFor(() => {
        expect(screen.getByLabelText("Environment")).toBeDisabled();
      });
      expect(verdictLine()).toHaveTextContent(
        "Planning in qa… each step's script runs in plan mode.",
      );
    });

    it("scenarios detail asks to choose an environment when only production is declared", async () => {
      // AC-596.2.2 / AC-596.2.3: never production unless picked; the select says to choose.
      renderDetail({
        [DETAIL]: graphDetail({
          environments: [{ name: "live", access: "read", production: true }],
        }),
      });
      const select = await screen.findByLabelText("Environment");
      expect(select).toHaveValue("");
      expect(
        within(select).getByRole("option", { name: "Choose an environment" }),
      ).toBeInTheDocument();
      expect(verdictLine()).toHaveTextContent("Choose an environment to plan in.");
      expect(within(runBar()).getByRole("button", { name: "Plan in …" })).toBeDisabled();
    });

    it("scenarios detail remembers the environment a plan was made in", async () => {
      // AC-596.2.3: the next visit opens on it.
      renderDetail({ [PLAN]: aScenarioPlan({ environment: "qa", access: "read" }) });
      await planIn("qa");
      await within(runBar()).findByText(/^Can start in qa/);

      const recent: unknown = JSON.parse(
        window.localStorage.getItem("ah.scenarios.env.demo") ?? "[]",
      );
      expect(recent).toEqual(["qa"]);
    });

    it("scenarios detail words the scenario run mode in its control's title", async () => {
      // AC-596.2.4: the mode's stop, and that blocks that ask still pause.
      const user = userEvent.setup();
      renderDetail();
      const mode = await screen.findByRole("group", { name: "Scenario run mode" });
      const control = mode.closest("[title]");
      expect(control).toHaveAttribute(
        "title",
        "If a block does not reach its expected state, the scenario run pauses and a read-only agent investigates with you. Blocks that ask still pause for your approval.",
      );
      expect(within(mode).getByRole("button", { name: "Interactive" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      await user.click(within(mode).getByRole("button", { name: "Regression" }));
      expect(control).toHaveAttribute(
        "title",
        "No agent and no token cost. The first block that does not reach its expected state fails the scenario run. Blocks that ask still pause for your approval.",
      );
    });

    it("scenarios detail counts the inputs to fill and plans with Enter in them", async () => {
      // AC-596.2.5: Inputs · N to fill / N set toggles the values; Enter plans once.
      const user = userEvent.setup();
      const { requests } = renderDetail({ [PLAN]: aScenarioPlan() });
      await screen.findByText("No problems");
      const inputs = within(runBar()).getByRole("button", { name: "Inputs · 1 to fill" });
      expect(inputs).toHaveAttribute("aria-expanded", "false");
      await user.click(inputs);
      expect(inputs).toHaveAttribute("aria-expanded", "true");
      const form = screen.getByRole("form", { name: "Values to plan with" });
      expect(form).toHaveTextContent("Values to plan and start with");
      await user.type(within(form).getByRole("textbox", { name: "external_ref" }), "T-1");
      expect(within(runBar()).getByRole("button", { name: "Inputs · 1 set" })).toBeInTheDocument();

      await user.keyboard("{Enter}");
      await within(runBar()).findByText(/^Can start in personal/);
      expect(requests.filter((request) => request.url.endsWith("/plan"))).toHaveLength(1);
      expect(within(runBar()).getByRole("button", { name: "Plan again" })).toBeInTheDocument();
    });

    it("scenarios detail sends each input typed by its declaration, and keeps a bad one at its field", async () => {
      // AC-596.2.5: an integer input is sent as a number (a start checks the type as declared).
      const user = userEvent.setup();
      const { requests } = renderDetail({
        [DETAIL]: graphDetail({
          document: {
            ...GRAPH,
            inputs: { ...GRAPH.inputs, minutes: { type: "integer", required: true } },
          },
        }),
        [PLAN]: aScenarioPlan(),
      });
      await screen.findByText("No problems");
      await user.click(within(runBar()).getByRole("button", { name: "Inputs · 2 to fill" }));
      const form = screen.getByRole("form", { name: "Values to plan with" });
      await user.type(within(form).getByRole("textbox", { name: "external_ref" }), "T-1");
      const minutes = within(form).getByRole("spinbutton", { name: "minutes" });
      await user.type(minutes, "1.5");
      await user.click(within(form).getByRole("button", { name: "Plan in personal" }));

      expect(minutes).toHaveAccessibleDescription("minutes must be a whole number.");
      expect(requests.some((request) => request.url.endsWith("/plan"))).toBe(false);

      await user.clear(minutes);
      await user.type(minutes, "3");
      await user.click(within(form).getByRole("button", { name: "Plan in personal" }));
      await within(runBar()).findByText(/^Can start in personal/);
      const sent = requests.find((request) => request.url.endsWith("/plan"));
      expect(await sent?.clone().json()).toEqual({
        environment: "personal",
        inputs: { external_ref: "T-1", minutes: 3 },
      });
    });

    it("scenarios detail says a plan is still planning after 10 s", async () => {
      // AC-596.2.6 (restored from v0.26.0): the Planning state names when a plan stops.
      vi.useFakeTimers({ shouldAdvanceTime: true });
      renderDetail({ [PLAN]: "pending" });
      await planIn("personal");
      await within(runBar()).findByText(/^Planning in personal…/);
      expect(verdictLine()).not.toHaveTextContent("Still planning");

      act(() => {
        vi.advanceTimersByTime(10_000);
      });
      expect(verdictLine()).toHaveTextContent(
        "Planning in personal… each step's script runs in plan mode. Still planning. A plan stops after 5 min.",
      );
    });

    it("scenarios detail counts a plan's problems in the verdict and lists them in This plan", async () => {
      // AC-596.2.7 / AC-596.2.19: the problem count on the verdict and Start; each problem.
      renderDetail({ [PLAN]: aScenarioPlan({ problems: ["external_ref is not a ref"] }) });
      await planIn("personal");

      expect(
        await within(runBar()).findByText("Cannot start: the plan has 1 problem."),
      ).toBeInTheDocument();
      expect(startButton()).toHaveAttribute("title", "Cannot start: the plan has 1 problem.");
      const plan = within(runPanel()).getByRole("region", { name: "This plan" });
      expect(within(plan).getByText("external_ref is not a ref")).toBeInTheDocument();
    });

    it("scenarios detail names the terminal command when hub web cannot launch a start", async () => {
      // AC-596.2.8: a 502 start says how to see why from a terminal.
      renderDetail({
        [PLAN]: aScenarioPlan(),
        [START]: aProblem({ status: 502, title: "Bad gateway" }),
      });
      const user = await planIn("personal");
      await within(runBar()).findByText(/^Can start in personal/);
      await user.click(startButton());
      const dialog = screen.getByRole("alertdialog", { name: "Start a scenario run in personal?" });
      await user.click(within(dialog).getByRole("button", { name: "Start scenario run" }));

      expect(
        await within(dialog).findByText(
          codeText("./hub scenario run order-lifecycle --env personal"),
        ),
      ).toBeInTheDocument();
      expect(dialog).toHaveTextContent("hub web could not launch hub scenario run.");
    });

    it("scenarios detail marks a plan stale once the environment changes", async () => {
      // AC-596.2.9 / AC-596.2.19: the verdict says why, Start stays off, This plan says so.
      renderDetail({ [PLAN]: aScenarioPlan() });
      const user = await planIn("personal");
      await within(runBar()).findByText(/^Can start in personal/);

      await user.selectOptions(screen.getByLabelText("Environment"), "qa");
      expect(verdictLine()).toHaveTextContent(
        "This plan is for personal. Plan again to start in qa.",
      );
      expect(startButton()).toBeDisabled();
      expect(within(runBar()).getByRole("button", { name: "Plan in qa" })).toBeInTheDocument();
      expect(within(runPanel()).getByRole("region", { name: "This plan" })).toHaveTextContent(
        "Planned before your changes: plan again to start.",
      );
    });

    it("scenarios detail marks a plan stale when an input changes", async () => {
      // AC-596.2.34: a start never sends the values the plan was not made with.
      renderDetail({ [PLAN]: aScenarioPlan() });
      const user = await planIn("personal");
      await within(runBar()).findByText(/^Can start in personal/);

      await user.click(within(runBar()).getByRole("button", { name: "Inputs · 1 set" }));
      const form = screen.getByRole("form", { name: "Values to plan with" });
      await user.type(within(form).getByRole("textbox", { name: "external_ref" }), "2");

      expect(verdictLine()).toHaveTextContent(
        "This plan is for external_ref T-1. Plan again to start with the new values.",
      );
      expect(startButton()).toBeDisabled();
    });

    it("scenarios detail words a stale plan made with no values", async () => {
      // AC-596.2.34: a plan with no inputs never reads "This plan is for ."
      const user = userEvent.setup();
      renderDetail({
        [DETAIL]: graphDetail({ document: { ...GRAPH, inputs: { note: { type: "string" } } } }),
        [PLAN]: aScenarioPlan(),
      });
      await screen.findByText("No problems");
      await user.click(within(runBar()).getByRole("button", { name: "Plan in personal" }));
      const form = screen.getByRole("form", { name: "Values to plan with" });
      await user.click(within(form).getByRole("button", { name: "Plan in personal" }));
      await within(runBar()).findByText(/^Can start in personal/);

      await user.click(within(runBar()).getByRole("button", { name: "Inputs · 1 to fill" }));
      await user.type(
        within(screen.getByRole("form", { name: "Values to plan with" })).getByRole("textbox", {
          name: "note",
        }),
        "x",
      );
      expect(verdictLine()).toHaveTextContent(
        "This plan was made with no values. Plan again to start with the new values.",
      );
      expect(verdictLine()).not.toHaveTextContent("This plan is for .");
    });

    it("scenarios detail clears a plan, its verdict and its row lines", async () => {
      // AC-596.2.10.
      const user = userEvent.setup();
      renderDetail({ [PLAN]: aScenarioPlan() });
      await planIn("personal");
      await within(runBar()).findByText(/^Can start in personal/);
      expect(row(/^Step 1,/)).toHaveTextContent("Plan:");

      await user.click(within(runBar()).getByRole("button", { name: "Clear plan" }));
      expect(within(runPanel()).queryByRole("region", { name: "This plan" })).toBeNull();
      expect(verdictLine()).toHaveTextContent(
        "Plan the scenario to see what each step will do in personal. Nothing is changed by a plan.",
      );
      expect(row(/^Step 1,/)).not.toHaveTextContent("Plan:");
      expect(startButton()).toHaveAttribute("title", "Plan the scenario first.");
    });

    it("scenarios detail on a tablet plans but says starting needs a desktop screen", async () => {
      // AC-596.2.8 (restored from v0.26.0, spec 23 Responsive): a tablet gets the plan only.
      vi.stubGlobal("matchMedia", (query: string) => ({
        matches: query === "(min-width: 768px) and (max-width: 1279px)",
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      }));
      renderDetail({ [PLAN]: aScenarioPlan() });
      await planIn("personal");

      expect(await within(runBar()).findByText(/^Can start in personal/)).toBeInTheDocument();
      expect(
        within(runBar()).getByText("Starting a scenario run needs a desktop screen."),
      ).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Start scenario run" })).toBeNull();
    });

    it("scenarios detail names an undeclared environment and the command that declares it", async () => {
      // AC-596.2.2 (restored from v0.26.0): an old ?env= naming an environment the hub lacks.
      renderDetail({}, `${PATH}?env=staging`);

      const select = await screen.findByLabelText("Environment");
      expect(select).toHaveValue("staging");
      expect(verdictLine()).toHaveTextContent("Environment staging is not declared in this hub.");
      expect(within(runPanel()).getByRole("alert")).toHaveTextContent(
        "Environment staging is not declared in this hub. Declare it in hub.json, or in hub.local.json for yourself:",
      );
      expect(
        within(runPanel()).getByText(codeText("./hub env add staging --access read")),
      ).toBeInTheDocument();
      expect(startButton()).toHaveAttribute(
        "title",
        "Environment staging is not declared in this hub.",
      );
    });

    it("scenarios detail names an environment a plan finds undeclared", async () => {
      // AC-596.2.7 (restored from v0.26.0): a plan with no access is for no declared environment.
      renderDetail({
        [PLAN]: aScenarioPlan({ environment: "qa", access: null, denied: true, rows: [] }),
      });
      await planIn("qa");

      expect(
        await within(runPanel()).findByText(codeText("./hub env add qa --access read")),
      ).toBeInTheDocument();
      expect(verdictLine()).toHaveTextContent("Environment qa is not declared in this hub.");
      expect(startButton()).toBeDisabled();
    });

    it("scenarios detail shows a plan's input problems at their fields", async () => {
      // AC-596.2.5 (restored from v0.26.0): a 422 names its inputs by pointer.
      renderDetail({
        [PLAN]: aProblem({
          status: 422,
          title: "Invalid request body",
          errors: [{ pointer: "/inputs/external_ref", message: "external_ref must be a ref." }],
        }),
      });
      await planIn("personal");

      const form = await screen.findByRole("form", { name: "Values to plan with" });
      await waitFor(() => {
        expect(
          within(form).getByRole("textbox", { name: "external_ref" }),
        ).toHaveAccessibleDescription("external_ref must be a ref.");
      });
      // Every message sits at a field: no problem banner repeats it.
      expect(within(runPanel()).queryByText("Could not plan the scenario")).toBeNull();
    });

    it("scenarios detail shows a plan 422's messages that name no field of the form", async () => {
      // AC-596.2.5 (restored from v0.26.0): none of the messages is lost.
      renderDetail({
        [PLAN]: aProblem({
          status: 422,
          title: "Invalid request body",
          errors: [
            { pointer: "/inputs/external_ref", message: "external_ref must be a ref." },
            { pointer: "/environment", message: "environment must name an environment." },
            {
              pointer: "/inputs/added_later",
              message: "added_later is not an input of the scenario.",
            },
          ],
        }),
      });
      await planIn("personal");

      expect(
        await within(runPanel()).findByText("environment must name an environment."),
      ).toBeInTheDocument();
      // An input the form does not show (one added later) keeps its message too.
      expect(
        within(runPanel()).getByText("added_later is not an input of the scenario."),
      ).toBeInTheDocument();
      const form = screen.getByRole("form", { name: "Values to plan with" });
      expect(
        within(form).getByRole("textbox", { name: "external_ref" }),
      ).toHaveAccessibleDescription("external_ref must be a ref.");
    });
  });

  describe("run panel", () => {
    it("scenarios detail folds the draft actions and commits only those it adds, at once", async () => {
      // AC-596.2.39 / AC-596.2.40: one commit command, folded under the actions it adds.
      const commit = (name: string) =>
        `git add -- actions/orders/${name}.yaml && git commit -m 'Accept action orders/${name}'`;
      const draft = (name: string, command: string | null) =>
        aScenarioAction({ ref: `orders/${name}`, name, draft: true, accept_command: command });
      renderDetail({
        [DETAIL]: graphDetail({
          actions: [
            draft("send-queue-message", commit("send-queue-message")),
            draft("get-order-by-ref", commit("get-order-by-ref")),
            draft("render-invoice-pdf", null),
          ],
        }),
      });

      const before = await screen.findByRole("region", { name: "Before you start" });
      expect(before).toHaveTextContent("3 draft actions to commit");
      expect(before).toHaveTextContent("these actions are committed in the hub checkout");
      // Its copy button sits outside the fold.
      const [copy] = within(before).getAllByRole("button", { name: "Copy the commit command" });
      expect(copy?.closest("details")).toBeNull();
      const folded = before.querySelector("details");
      expect(folded).not.toHaveAttribute("open");
      expect(within(before).getByText("Which actions (3) and the command")).toBeInTheDocument();
      expect(within(before).getAllByRole("listitem")).toHaveLength(3);
      // The message names only the actions whose files it adds.
      expect(
        within(before).getByText(
          codeText(
            "git add -- actions/orders/send-queue-message.yaml actions/orders/get-order-by-ref.yaml && git commit -m 'Accept actions orders/send-queue-message, orders/get-order-by-ref'",
          ),
        ),
      ).toBeInTheDocument();
    });

    it("scenarios detail reaches Before you start from the verdict while a step is open", async () => {
      // AC-596.2.7: the verdict's link lands even when the editor holds the right column.
      renderDetail({ [PLAN]: denied });
      const user = await planIn("personal");
      const link = await within(runBar()).findByRole("link", {
        name: /^Cannot start: 1 draft action needs acceptance/,
      });
      await user.click(row(/^Step 1,/));
      expect(
        screen.queryByRole("complementary", { name: "Scenario runs of order-lifecycle" }),
      ).toBeNull();

      await user.click(link);
      expect(within(runPanel()).getByRole("region", { name: "Before you start" })).toHaveFocus();
    });

    it("scenarios detail lists the newest five scenario runs, then all of them", async () => {
      // AC-596.2.20.
      const user = userEvent.setup();
      const runs = Array.from({ length: 6 }, (_, i) =>
        aScenarioRunRef({ run_id: `run-${String(i)}`, status: "done", ended_at: at(60) }),
      );
      renderDetail({ [DETAIL]: graphDetail({ runs }) });

      const list = await screen.findByRole("region", { name: "Scenario runs" });
      expect(within(list).getAllByRole("link", { name: /^Open scenario run/ })).toHaveLength(5);
      await user.click(within(list).getByRole("button", { name: "Show all 6" }));
      expect(within(list).getAllByRole("link", { name: /^Open scenario run/ })).toHaveLength(6);
      await user.click(within(list).getByRole("button", { name: "Show fewer" }));
      expect(within(list).getAllByRole("link", { name: /^Open scenario run/ })).toHaveLength(5);
    });
  });

  describe("scenario run on the blocks", () => {
    it("scenarios detail says where a scenario run waits for you, on the strip and its block", async () => {
      // AC-596.2.13.
      const gate = anApproval({
        id: `${SCENARIO_RUN}:fetch-order--2__ask:1`,
        gate_id: `${SCENARIO_RUN}:fetch-order--2__ask:1`,
        session_id: `run:${SCENARIO_RUN}`,
        kind: "human_gate",
        project: "demo",
        gate_kind: "policy",
        path: null,
        rule: null,
      });
      renderDetail({
        [DETAIL]: treeDetail({ runs: [aScenarioRunRef({ status: "running" })] }),
        "/api/v1/approvals": aPage([gate]),
        "/api/v1/workflow-runs": aPage([aScenarioWorkflowRun()]),
        [WORKFLOW_RUN]: aScenarioWorkflowRun(),
        [SCENARIO_RUN_RECORD]: aDebugScenarioRun({
          debug: null,
          breakpoints: [],
          timeline: [
            { event: "start", node: null, attempt: null, status: null, at: at(0), block: null },
            line("step_start", "1.1", 5),
            line("step_end", "1.1", 10, "ok"),
          ],
          polls: [],
          captures: [],
          blocks: RUN_BLOCKS,
        }),
      });

      const strip = await screen.findByRole("region", { name: `Scenario run ${SCENARIO_RUN}` });
      await waitFor(() => {
        expect(within(strip).getByRole("status")).toHaveTextContent(
          /waits for you at block 1\.2: an approval/,
        );
      });
      expect(row(/^Step 1\.2,/)).toHaveTextContent("Waiting for you: approval");
      expect(row(/^Step 1\.2,/)).toHaveAttribute("aria-current", "step");
    });

    it("scenarios detail writes a breakpoint toggled on a live scenario run to the run", async () => {
      // AC-596.2.15: the run's whole set, in block order.
      const user = userEvent.setup();
      const { requests } = renderDetail({
        [DETAIL]: treeDetail({ runs: [aScenarioRunRef({ status: "running" })] }),
        [WORKFLOW_RUN]: aScenarioWorkflowRun(),
        [SCENARIO_RUN_RECORD]: aDebugScenarioRun({
          debug: null,
          breakpoints: ["1.2"],
          timeline: [
            { event: "start", node: null, attempt: null, status: null, at: at(0), block: null },
            line("step_start", "1.1", 5),
          ],
          blocks: RUN_BLOCKS,
        }),
        [`PUT ${SCENARIO_RUN_RECORD}/breakpoints`]: { blocks: ["1.1", "1.2"] },
      });

      const first = await screen.findByRole("button", { name: "Breakpoint before block 1.1 (b)" });
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: "Breakpoint before block 1.2 (b)" }),
        ).toHaveAttribute("aria-pressed", "true");
      });
      await user.click(first);

      const put = await waitFor(() => {
        const found = requests.find((request) => request.method === "PUT");
        expect(found).toBeDefined();
        return found;
      });
      expect(new URL(put?.url ?? "").pathname).toBe(`${SCENARIO_RUN_RECORD}/breakpoints`);
      expect(await put?.clone().json()).toEqual({ blocks: ["1.1", "1.2"] });
      await waitFor(() => {
        expect(first).toHaveAttribute("aria-pressed", "true");
      });
    });

    it("scenarios detail lays no state on the blocks for a scenario run of an older revision", async () => {
      // AC-596.2.17: its states are on its own page.
      const user = userEvent.setup();
      renderDetail({
        [DETAIL]: graphDetail({
          revision: 2,
          runs: [aScenarioRunRef({ status: "done", ended_at: at(60) })],
        }),
        [WORKFLOW_RUN]: aScenarioWorkflowRun({
          status: "done",
          revision: 1,
          steps: [
            {
              attempt: 1,
              ended_at: at(30),
              key: "fetch-order",
              max_attempts: 1,
              reason: null,
              session_ids: [],
              started_at: at(5),
              status: "ok",
            },
          ],
        }),
        [SCENARIO_RUN_RECORD]: aScenarioRunDetail(),
      });

      const runs = await screen.findByRole("region", { name: "Scenario runs" });
      await user.click(within(runs).getByRole("button", { name: "Show" }));
      const strip = await screen.findByRole("region", { name: `Scenario run ${SCENARIO_RUN}` });
      expect(within(strip).getByRole("status")).toHaveTextContent(
        "it ran an older revision of the file, so its states are on its page",
      );
      expect(row(/^Step 1,/)).not.toHaveTextContent("Last run:");
    });

    it("scenarios detail toggles a block's breakpoint with b on its row", async () => {
      // AC-596.2.24.
      const user = userEvent.setup();
      renderDetail({ [DETAIL]: treeDetail() });
      const toggle = await screen.findByRole("button", { name: "Breakpoint before block 1.2 (b)" });
      expect(toggle).toHaveAttribute("aria-pressed", "false");

      row(/^Step 1\.2,/).focus();
      await user.keyboard("b");
      expect(toggle).toHaveAttribute("aria-pressed", "true");
      await user.keyboard("b");
      expect(toggle).toHaveAttribute("aria-pressed", "false");
    });
  });

  describe("states", () => {
    it("scenarios detail states: not found", async () => {
      renderDetail({ [DETAIL]: aProblem({ status: 404, title: "Not found" }) });

      expect(await screen.findByText("Scenario order-lifecycle not found")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Go to Scenarios" })).toHaveAttribute(
        "href",
        "/scenarios",
      );
    });

    it("scenarios detail states: a problem with Try again", async () => {
      renderDetail({ [DETAIL]: aProblem({ status: 500, detail: "boom" }) });

      expect(await screen.findByText("Could not load the scenario")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    });

    it("scenarios detail states: no scenario runs yet", async () => {
      renderDetail();

      expect(
        await screen.findByText("No scenario runs yet. Plan, then start one from the bar above."),
      ).toBeInTheDocument();
      expect(verdictLine()).toHaveTextContent(
        "Plan the scenario to see what each step will do in personal. Nothing is changed by a plan.",
      );
      expect(startButton()).toBeDisabled();
      expect(startButton()).toHaveAttribute("title", "Plan the scenario first.");
    });

    it("scenarios detail states: run control off renders the plan's problem", async () => {
      renderDetail({
        [PLAN]: aProblem({
          status: 404,
          title: "Run control off",
          detail: "Run control is off in this container.",
          type: "urn:agent-hub:problem:run-control-off",
        }),
      });
      await planIn("personal");

      expect(
        await within(runPanel()).findByText(
          /Plans and scenario runs cannot start from the agent-hub container/,
        ),
      ).toBeInTheDocument();
      expect(verdictLine()).toHaveTextContent(
        "Could not plan: Run control is off in this container.",
      );
      expect(within(runBar()).getByRole("button", { name: "Plan in personal" })).toBeDisabled();
    });

    it("scenarios detail states: hub.local.json invalid, locked and too slow", async () => {
      const { unmount } = renderDetail({
        [PLAN]: aProblem({ status: 409, title: "x", code: "hub_local_invalid" }),
      });
      await planIn("personal");
      expect(await screen.findByText(/so the environments are unknown/)).toBeInTheDocument();
      unmount();

      const locked = renderDetail({ [PLAN]: aProblem({ status: 401, title: "Unauthorized" }) });
      await planIn("personal");
      expect(await screen.findByText(/Planning is locked in this browser/)).toBeInTheDocument();
      locked.unmount();

      renderDetail({ [PLAN]: aProblem({ status: 502, title: "Bad gateway" }) });
      await planIn("qa");
      expect(await screen.findByText(/The plan did not finish in 5 min/)).toBeInTheDocument();
      expect(
        screen.getByText(codeText("./hub scenario plan order-lifecycle --env qa")),
      ).toBeInTheDocument();
    });
  });

  it("scenarios detail has no serious a11y violation with a plan shown (a11y)", async () => {
    const { container } = renderDetail({ [DETAIL]: treeDetail(), [PLAN]: denied });
    await planIn("personal");
    await within(runBar()).findByText(/^Cannot start: 1 draft action needs acceptance/);
    expect(within(runPanel()).getByRole("region", { name: "This plan" })).toBeInTheDocument();

    expect(await seriousViolations(container)).toEqual([]);
  });

  it("scenarios detail has no serious a11y violation with breakpoint toggles (a11y)", async () => {
    const { container } = renderDetail({ [DETAIL]: treeDetail() });
    const toggle = await screen.findByRole("button", { name: "Breakpoint before block 1.2 (b)" });
    await userEvent.setup().click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");

    expect(await seriousViolations(container)).toEqual([]);
  });
});
