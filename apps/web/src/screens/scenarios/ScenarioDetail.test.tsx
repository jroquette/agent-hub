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
  aScenarioDetail,
  aScenarioRunDetail,
  FakeEventSource,
  aScenarioPlan,
  aScenarioPlanRow,
  aScenarioRunRef,
  aTreeDocument,
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

const denied = aScenarioPlan({
  denied: true,
  rows: [...aScenarioPlan().rows, aDraftRow()],
});

const routes: ApiRoutes = {
  [DETAIL]: aScenarioDetail(),
  "/api/v1/approvals": aPage([]),
  "/api/v1/workflow-runs": aPage([]),
};

// The page opens on the builder (Build); these tests read its Run mode.
function renderDetail(extra: ApiRoutes = {}, path = `${PATH}?mode=run`) {
  return renderWithApi(<ScenarioDetailScreen />, {
    routes: { ...routes, ...extra },
    path,
    route: "/scenarios/:project/:name",
  });
}

async function planIn(environment: string, ref = "T-1") {
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText("Environment"), environment);
  await user.type(screen.getByLabelText("external_ref (required)"), ref);
  await user.click(screen.getByRole("button", { name: `Plan in ${environment}` }));
  return user;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("ScenarioDetailScreen (scenarios detail)", () => {
  it("scenarios detail plans for a chosen environment (deny; needs acceptance with the commit line)", async () => {
    const { requests } = renderDetail({ [PLAN]: denied }, `${PATH}?mode=run&env=personal`);

    await screen.findByRole("heading", { name: "order-lifecycle" });
    // The plan never runs on load, even with ?env=.
    expect(requests.some((request) => request.method === "POST")).toBe(false);
    expect(screen.getByLabelText("Environment")).toHaveValue("personal");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("external_ref (required)"), "T-1");
    await user.click(screen.getByRole("button", { name: "Plan in personal" }));

    const render = await screen.findByRole("article", { name: "Step 3: render-pdf" });
    const sent = requests.find((request) => request.method === "POST");
    expect(await sent?.clone().json()).toEqual({
      environment: "personal",
      inputs: { external_ref: "T-1" },
    });
    expect(screen.getByText("personal · access write", { selector: "b" })).toBeInTheDocument();
    expect(screen.getByText("3 steps: 1 read, 2 write")).toBeInTheDocument();
    // The plan lays over the step cards: each one says its decision in personal.
    const fetch = screen.getByRole("article", { name: "Step 1: fetch-order" });
    expect(within(fetch).getByText(/Runs without asking in personal/)).toBeInTheDocument();
    expect(within(fetch).getByText("Sends FETCH_ORDERS for T-1")).toBeInTheDocument();
    expect(
      within(render).getByText(
        "Denied in personal: draft action: commit it to run. The scenario run cannot start.",
      ),
    ).toBeInTheDocument();
    expect(within(render).getByText("Draft: needs acceptance")).toBeInTheDocument();
    expect(within(render).getByText(aDraftRow().accept_command ?? "")).toBeInTheDocument();
    expect(
      within(render).getByRole("button", {
        name: "Copy the commit command for orders/render-invoice-pdf",
      }),
    ).toBeInTheDocument();
    expect(within(render).getByText("<$CTX.order_id from order-on-hold>")).toHaveAttribute(
      "title",
      "Known at run time: captured by step order-on-hold",
    );
    expect(within(render).getByText("runs with values known at run time.")).toBeInTheDocument();
    expect(screen.getByText("Cannot start: render-pdf is denied in personal.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start scenario run" })).toBeDisabled();
  });

  it("scenarios detail starts a scenario run after its confirm and stays to follow it once listed", async () => {
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
      [DETAIL]: () => aScenarioDetail({ runs: started ? [aScenarioRunRef()] : [] }),
    });
    const user = await planIn("personal");

    expect(
      await screen.findByText("Can start in personal. 1 step asks you before it runs."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Regression" }));
    await user.click(screen.getByRole("button", { name: "Start scenario run" }));
    const dialog = screen.getByRole("alertdialog", { name: "Start a scenario run in personal?" });
    expect(dialog).toHaveTextContent(
      "It runs 3 steps in personal: 1 read and 2 write. resolve-cover asks you before it runs. Regression mode: the first step that does not reach its expected state fails the scenario run.",
    );
    expect(within(dialog).getByRole("button", { name: "Back to plan" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Start scenario run" }));

    // Once listed, the dialog closes and the page stays: its scenario runs list it.
    const runs = screen.getByRole("region", { name: "Scenario runs" });
    expect(
      await within(runs).findByRole("link", { name: SCENARIO_RUN }, { timeout: 5000 }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(router.state.location.pathname).toBe(PATH);
    const start = requests.find(
      (request) => request.method === "POST" && request.url.endsWith("/runs"),
    );
    expect(await start?.clone().json()).toEqual({
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
    await user.click(await screen.findByRole("button", { name: "Start scenario run" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Start scenario run" }),
    );

    const alert = await screen.findByText("Could not start the scenario run");
    expect(alert.closest("[role=alert]")).toHaveTextContent(
      "step fetch-order: deny (access read in qa does not allow write)Nothing was started.",
    );
  });

  it("scenarios detail marks a plan stale when an input changes", async () => {
    renderDetail({ [PLAN]: aScenarioPlan() });
    const user = await planIn("personal");
    await screen.findByText("Can start in personal.");

    await user.type(screen.getByLabelText("external_ref (required)"), "2");

    expect(
      screen.getByText(
        "This plan is for personal with external_ref T-1. Plan again to start with the new values.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start scenario run" })).toBeDisabled();
  });

  it("scenarios detail names an undeclared environment and the command that declares it", async () => {
    const user = userEvent.setup();
    renderDetail({
      [DETAIL]: aScenarioDetail({ environments: [] }),
      [PLAN]: aScenarioPlan({ environment: "qa", access: null, denied: true, rows: [] }),
    });
    await user.type(await screen.findByLabelText("Environment"), "qa");
    await user.type(screen.getByLabelText("external_ref (required)"), "T-1");
    await user.click(screen.getByRole("button", { name: "Plan in qa" }));

    expect(
      await screen.findByText(/Environment qa is not declared in this hub\./),
    ).toBeInTheDocument();
    expect(screen.getByText("./hub env add qa --access read")).toBeInTheDocument();
  });

  it("scenarios detail shows the production banner and the denied steps", async () => {
    renderDetail({
      [PLAN]: aScenarioPlan({
        environment: "live",
        access: "read",
        production: true,
        denied: true,
        rows: [
          aScenarioPlanRow({
            decision: "deny",
            reason_kind: "production",
            reason: "live is a production environment: writes and destroys are denied",
          }),
          aScenarioPlanRow({
            step: "resolve-cover",
            decision: "deny",
            reason_kind: "production",
            reason: "live is a production environment: writes and destroys are denied",
          }),
        ],
      }),
    });
    await planIn("live");

    expect(
      await screen.findByText(
        "live is a production environment: writes and destroys are denied there.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Cannot start: fetch-order and resolve-cover are denied in live."),
    ).toBeInTheDocument();
  });

  it("scenarios detail reads each step in words before any plan, with its action and stops", async () => {
    renderDetail({ [DETAIL]: aScenarioDetail({ runs: [aScenarioRunRef({ status: "done" })] }) });

    const steps = await screen.findByRole("list", { name: "Steps of order-lifecycle" });
    const fetch = within(steps).getByRole("article", { name: "Step 1: fetch-order" });
    expect(
      within(fetch).getByText("Send one message to the orders queue, once."),
    ).toBeInTheDocument();
    expect(
      within(fetch).getByTitle("actions/orders/scripts/send_queue_message.py"),
    ).toBeInTheDocument();
    expect(within(fetch).getByText(/It changes data: it asks you first/)).toBeInTheDocument();
    expect(
      within(fetch).getByText(/pauses and a read-only agent investigates/),
    ).toBeInTheDocument();
    const held = within(steps).getByRole("article", { name: "Step 2: order-on-hold" });
    expect(within(held).getByText("Expect")).toBeInTheDocument();
    expect(within(steps).getByText("after fetch-order")).toBeInTheDocument();
    expect(screen.getByText("3 steps · writes in 2 steps · 1 input")).toBeInTheDocument();
    const runs = screen.getByRole("region", { name: "Scenario runs" });
    expect(within(runs).getByRole("link", { name: SCENARIO_RUN })).toHaveAttribute(
      "href",
      `${PATH}/runs/${SCENARIO_RUN}`,
    );
    expect(within(runs).getByText("personal")).toBeInTheDocument();
  });

  it("scenarios detail words an expect's wait and changes its stop with the mode", async () => {
    const user = userEvent.setup();
    renderDetail({
      [DETAIL]: aScenarioDetail({
        steps: [
          {
            id: "service-up",
            type: "expect",
            action: "get-order-by-ref",
            depends_on: [],
            with: { external_ref: "$INPUTS.external_ref" },
            every: "10s",
            timeout: "2m",
            until_when: "$self.output.status == 200",
          },
        ],
      }),
    });

    const card = await screen.findByRole("article", { name: "Step 1: service-up" });
    expect(
      within(card).getByText(
        "Waits until status is 200: checks every 10 s, for up to 2 min (at most 12 checks).",
      ),
    ).toBeInTheDocument();
    expect(within(card).getByText("input external_ref")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Regression" }));
    expect(
      within(card).getByText(
        "If its condition (status is 200) still does not hold after 2 min, the scenario run fails here (Regression).",
      ),
    ).toBeInTheDocument();
  });

  it("scenarios detail opens an action's panel with its script and shows the scenario file", async () => {
    const user = userEvent.setup();
    renderDetail();

    const fetch = await screen.findByRole("article", { name: "Step 1: fetch-order" });
    await user.click(within(fetch).getByRole("button", { name: "Open action send-queue-message" }));
    const panel = await screen.findByRole("complementary", { name: "Action send-queue-message" });
    expect(within(panel).getByText("print('{}')")).toBeInTheDocument();
    expect(
      within(panel).getByRole("table", { name: "Inputs of send-queue-message" }),
    ).toBeInTheDocument();
    await user.click(
      within(panel).getByRole("button", { name: "Close action send-queue-message" }),
    );

    await user.click(screen.getByRole("button", { name: "Document" }));
    expect(
      screen.getByLabelText("Text of scenarios/orders/order-lifecycle.yaml"),
    ).toHaveTextContent("kind: scenario");
    expect(screen.getByRole("button", { name: "Edit with Claude" })).toBeInTheDocument();
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
        path: `${PATH}?mode=run`,
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
        await screen.findByText("No scenario runs yet. Plan, then start one above."),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Plan the scenario to see what each step will do in an environment."),
      ).toBeInTheDocument();
    });

    it("scenarios detail states: run control off in the container", async () => {
      renderDetail({
        [PLAN]: aProblem({
          status: 404,
          title: "Run control off",
          type: "urn:agent-hub:problem:run-control-off",
        }),
      });
      await planIn("personal");

      expect(
        await screen.findByText(
          /Plans and scenario runs cannot start from the agent-hub container/,
        ),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Plan in personal" })).toBeDisabled();
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
      await planIn("personal");
      expect(await screen.findByText(/The plan did not finish in 5 min/)).toBeInTheDocument();
    });
  });

  it("scenarios detail has no serious a11y violation with a plan shown (a11y)", async () => {
    const { container } = renderDetail({ [PLAN]: denied });
    await planIn("personal");
    await screen.findByText("Cannot start: render-pdf is denied in personal.");

    expect(await seriousViolations(container)).toEqual([]);
  });
  it("scenarios detail never sends a second start, even after the scenario run is late", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { requests } = renderDetail({
      [PLAN]: aScenarioPlan(),
      [START]: { run_id: SCENARIO_RUN, project: "demo", action: "start" },
    });
    const user = await planIn("personal");
    await user.click(await screen.findByRole("button", { name: "Start scenario run" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Start scenario run" }),
    );
    await screen.findByText("Started. Waiting for the scenario run's first event…");

    act(() => {
      vi.advanceTimersByTime(31_000);
    });

    const dialog = await screen.findByRole("dialog", { name: "Start a scenario run in personal?" });
    expect(within(dialog).getByText(/has not reported in 30 s/)).toBeInTheDocument();
    // The first dialog is gone, and nothing on the page can send a second start (review Q1).
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(
      screen
        .queryAllByRole("button", { name: "Start scenario run" })
        .filter((button) => !(button as HTMLButtonElement).disabled),
    ).toHaveLength(0);
    expect(within(dialog).queryByRole("button", { name: "Start scenario run" })).toBeNull();
    expect(
      within(dialog).getByRole("link", { name: `Open scenario run ${SCENARIO_RUN} anyway` }),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Back to plan" })).toBeEnabled();
    await user.click(within(dialog).getByRole("button", { name: "Back to plan" }));
    expect(screen.getByRole("button", { name: "Start scenario run" })).toBeDisabled();
    const starts = requests.filter((r) => r.method === "POST" && r.url.endsWith("/runs"));
    expect(starts).toHaveLength(1);
  });

  it("scenarios detail on a tablet plans but says starting needs a desktop screen", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query === "(min-width: 768px) and (max-width: 1279px)",
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
    renderDetail({ [PLAN]: aScenarioPlan() });
    await planIn("personal");

    expect(await screen.findByText("Can start in personal.")).toBeInTheDocument();
    expect(screen.getByText("Starting a scenario run needs a desktop screen.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start scenario run" })).toBeNull();
  });
  it("scenarios detail puts a draft's commit line in its step's card", async () => {
    renderDetail({ [PLAN]: denied });
    await planIn("personal");

    const render = await screen.findByRole("article", { name: "Step 3: render-pdf" });
    await within(render).findByText("Draft: needs acceptance");
    const command = within(render).getByText(aDraftRow().accept_command ?? "");
    expect(command).toHaveStyle({ whiteSpace: "pre-wrap" });
    const fetch = screen.getByRole("article", { name: "Step 1: fetch-order" });
    expect(within(fetch).queryByText("Draft: needs acceptance")).not.toBeInTheDocument();
  });

  it("scenarios detail shows a plan's input problems at their fields", async () => {
    renderDetail({
      [PLAN]: aProblem({
        status: 422,
        title: "Invalid request body",
        errors: [{ pointer: "/inputs/external_ref", message: "external_ref must be a ref." }],
      }),
    });
    await planIn("personal");

    await waitFor(() => {
      expect(screen.getByLabelText("external_ref (required)")).toHaveAccessibleDescription(
        /external_ref must be a ref\./,
      );
    });
  });

  it("scenarios detail names the environment in the slow-plan command", async () => {
    renderDetail({ [PLAN]: aProblem({ status: 502, title: "Bad gateway" }) });
    await planIn("qa");
    expect(
      await screen.findByText("./hub scenario plan order-lifecycle --env qa"),
    ).toBeInTheDocument();
  });

  it("scenarios detail names why a denied plan with no denied step cannot start", async () => {
    renderDetail({ [PLAN]: aScenarioPlan({ denied: true }) });
    await planIn("personal");

    expect(
      await screen.findByText("Cannot start in personal: the plan does not allow a start there."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Cannot start: +is denied/)).toBeNull();
  });
  it("scenarios detail shows a plan 422's messages that name no field of the form", async () => {
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

    expect(await screen.findByText("environment must name an environment.")).toBeInTheDocument();
    // An input the form does not show (one added later) keeps its message too (review Q4).
    expect(screen.getByText("added_later is not an input of the scenario.")).toBeInTheDocument();
    expect(screen.getByLabelText("external_ref (required)")).toHaveAccessibleDescription(
      /external_ref must be a ref\./,
    );
  });

  it("scenarios detail follows a running scenario run: banner with cancel and each step's status", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
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
      [DETAIL]: aScenarioDetail({ runs: [aScenarioRunRef({ status: "running" })] }),
      [`/api/v1/workflow-runs/${SCENARIO_RUN}`]: aRun({
        id: SCENARIO_RUN,
        kind: "scenario",
        workflow: "scenario:order-lifecycle",
        content_hash: "sha256:5f0c2e1d",
        revision: 1,
        status: "running",
        steps: [step("fetch-order", "ok"), step("order-on-hold", "running")],
      }),
      [`/api/v1/scenario-runs/${SCENARIO_RUN}`]: aScenarioRunDetail({
        polls: [1, 2, 3].map((poll) => ({
          node: "order-on-hold",
          attempt: 1,
          poll,
          held: false,
          at: null,
        })),
      }),
    });

    expect(await screen.findByText(/is running in personal/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open scenario run/ })).toHaveAttribute(
      "href",
      `${PATH}/runs/${SCENARIO_RUN}`,
    );
    expect(screen.getByRole("button", { name: /Cancel scenario run/ })).toBeInTheDocument();
    const fetch = screen.getByRole("article", { name: "Step 1: fetch-order" });
    expect(within(fetch).getByText("Done")).toBeInTheDocument();
    const held = screen.getByRole("article", { name: "Step 2: order-on-hold" });
    expect(await within(held).findByText(/Running · check 3/)).toBeInTheDocument();
    const render = screen.getByRole("article", { name: "Step 3: render-pdf" });
    expect(within(render).getByText("Not started")).toBeInTheDocument();
  });

  it("scenarios detail puts the run panel beside the steps", async () => {
    renderDetail();

    const panel = await screen.findByRole("complementary", { name: "Run order-lifecycle" });
    expect(panel).toHaveClass("sc-run-panel");
    expect(within(panel).getByRole("region", { name: "Run it" })).toBeInTheDocument();
    expect(within(panel).getByRole("region", { name: "Scenario runs" })).toBeInTheDocument();
  });
  it("scenarios detail sets breakpoints on a scenario written as blocks and starts with them", async () => {
    // A tree whose blocks run under the ids of the step cards; the stage holds no card.
    const tree = aScenarioDetail({
      version: 2,
      blocks: [
        { address: "1", kind: "stage", label: "Fetch", entry_nodes: ["fetch-order"] },
        { address: "1.1", kind: "do", label: "send-queue-message", entry_nodes: ["fetch-order"] },
        {
          address: "1.2",
          kind: "wait_until",
          label: "get-order-by-ref",
          entry_nodes: ["order-on-hold"],
        },
        { address: "1.3", kind: "do", label: "render-invoice-pdf", entry_nodes: ["render-pdf"] },
      ],
    });
    const { requests } = renderDetail({
      [DETAIL]: tree,
      [PLAN]: aScenarioPlan(),
      [START]: { run_id: SCENARIO_RUN, project: "demo", action: "start" },
    });

    const held = await screen.findByRole("article", { name: "Step 2: order-on-hold" });
    const toggle = within(held).getByRole("button", { name: "Breakpoint before block 1.2" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    const user = userEvent.setup();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    await planIn("personal");
    await user.click(await screen.findByRole("button", { name: "Start scenario run" }));
    const dialog = screen.getByRole("alertdialog", { name: "Start a scenario run in personal?" });
    expect(dialog).toHaveTextContent("It pauses before block 1.2, its breakpoint.");
    await user.click(within(dialog).getByRole("button", { name: "Start scenario run" }));
    await waitFor(() => {
      expect(requests.some((r) => r.method === "POST" && r.url.endsWith("/runs"))).toBe(true);
    });
    const start = requests.find((r) => r.method === "POST" && r.url.endsWith("/runs"));
    expect(await start?.clone().json()).toEqual({
      environment: "personal",
      inputs: { external_ref: "T-1" },
      mode: "interactive",
      breakpoints: ["1.2"],
    });

    // A production environment takes no breakpoint: none is offered there.
    await user.selectOptions(screen.getByLabelText("Environment"), "live");
    expect(within(held).queryByRole("button", { name: /^Breakpoint before/ })).toBeNull();
  });

  it("scenarios detail follows a scenario run in a debug pause: the banner names the block", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    renderDetail({
      [DETAIL]: aScenarioDetail({ runs: [aScenarioRunRef({ status: "running" })] }),
      [`/api/v1/workflow-runs/${SCENARIO_RUN}`]: aRun({
        id: SCENARIO_RUN,
        kind: "scenario",
        workflow: "scenario:order-lifecycle",
        content_hash: "sha256:5f0c2e1d",
        revision: 1,
        status: "running",
        steps: [],
      }),
      [`/api/v1/scenario-runs/${SCENARIO_RUN}`]: aDebugScenarioRun(),
    });

    expect(
      await screen.findByText(/is paused before block 2\.1 at its breakpoint, in personal/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open scenario run/ })).toHaveAttribute(
      "href",
      `${PATH}/runs/${SCENARIO_RUN}`,
    );
  });

  it("scenarios detail breaks long ids only after a slash or a dash", async () => {
    renderDetail();

    const render = await screen.findByRole("article", { name: "Step 3: render-pdf" });
    const action = within(render).getByText("render-invoice-pdf", { selector: ".ah-mono" });
    expect(action.querySelectorAll("wbr").length).toBe(2);
  });
});
