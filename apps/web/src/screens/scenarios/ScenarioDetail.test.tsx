import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aDraftRow,
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
    expect(screen.getAllByText(COMMIT)).toHaveLength(1);
    expect(within(before).getByText(COMMIT)).toBeInTheDocument();
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
      expect(screen.getByText("./hub scenario plan order-lifecycle --env qa")).toBeInTheDocument();
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
