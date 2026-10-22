import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aDraftRow,
  aPage,
  aProblem,
  aScenarioDetail,
  aScenarioPlan,
  aScenarioPlanRow,
  aScenarioRunRef,
  renderWithApi,
  SCENARIO_RUN,
  type ApiRoutes,
} from "../../testing/builders";
import { ScenarioDetailScreen } from ".";

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

function renderDetail(extra: ApiRoutes = {}, path = PATH) {
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
    const { requests } = renderDetail({ [PLAN]: denied }, `${PATH}?env=personal`);

    await screen.findByRole("heading", { name: "order-lifecycle" });
    // The plan never runs on load, even with ?env=.
    expect(requests.some((request) => request.method === "POST")).toBe(false);
    expect(screen.getByLabelText("Environment")).toHaveValue("personal");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("external_ref (required)"), "T-1");
    await user.click(screen.getByRole("button", { name: "Plan in personal" }));

    const table = await screen.findByRole("table", { name: "Plan of order-lifecycle in personal" });
    const sent = requests.find((request) => request.method === "POST");
    expect(await sent?.clone().json()).toEqual({
      environment: "personal",
      inputs: { external_ref: "T-1" },
    });
    expect(screen.getByText("personal · access write", { selector: "b" })).toBeInTheDocument();
    expect(screen.getByText("3 steps: 1 read, 2 write")).toBeInTheDocument();
    expect(within(table).getAllByText("Allow")).toHaveLength(2);
    expect(within(table).getByText("Denied")).toBeInTheDocument();
    expect(within(table).getByText("Draft action: commit it to run.")).toBeInTheDocument();
    expect(within(table).getByText("Draft: needs acceptance")).toBeInTheDocument();
    expect(within(table).getByText(aDraftRow().accept_command ?? "")).toBeInTheDocument();
    expect(
      within(table).getByRole("button", {
        name: "Copy the commit command for orders/render-invoice-pdf",
      }),
    ).toBeInTheDocument();
    expect(within(table).getByText("<$CTX.order_id from order-on-hold>")).toHaveAttribute(
      "title",
      "Known at run time: captured by step order-on-hold",
    );
    expect(within(table).getByText("Runs with values known at run time")).toBeInTheDocument();
    expect(within(table).getByText(/\(every 10s, up to 5m\)/)).toBeInTheDocument();
    expect(screen.getByText("Cannot start: render-pdf is denied in personal.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start scenario run" })).toBeDisabled();
  });

  it("scenarios detail starts a scenario run after its confirm and opens it once listed", async () => {
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

    await waitFor(
      () => {
        expect(router.state.location.pathname).toBe(`${PATH}/runs/${SCENARIO_RUN}`);
      },
      { timeout: 5000 },
    );
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

  it("scenarios detail lists the steps step by step and its scenario runs", async () => {
    renderDetail({ [DETAIL]: aScenarioDetail({ runs: [aScenarioRunRef({ status: "done" })] }) });

    const steps = await screen.findByRole("region", { name: "Step by step" });
    expect(steps).toHaveTextContent("fetch-orderAction send-queue-message");
    expect(steps).toHaveTextContent("order-on-holdExpect get-order-by-ref · after fetch-order");
    const runs = screen.getByRole("region", { name: "Scenario runs" });
    expect(within(runs).getByRole("link", { name: SCENARIO_RUN })).toHaveAttribute(
      "href",
      `${PATH}/runs/${SCENARIO_RUN}`,
    );
    expect(within(runs).getByText("personal · interactive")).toBeInTheDocument();
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

      expect(await screen.findByText("No scenario runs yet.")).toBeInTheDocument();
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
    await screen.findByRole("table", { name: "Plan of order-lifecycle in personal" });

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
});
