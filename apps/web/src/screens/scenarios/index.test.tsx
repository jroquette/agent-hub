import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aPage,
  aProblem,
  aRun,
  anApproval,
  aScenarioCatalog,
  aScenarioRunRef,
  aScenarioSummary,
  aWorkflowProblem,
  renderWithApi,
  SCENARIO_RUN,
  type ApiRoutes,
} from "../../testing/builders";
import { ScenariosScreen } from ".";

const waitingGate = anApproval({
  id: `${SCENARIO_RUN}:order-processed__investigation:1`,
  gate_id: `${SCENARIO_RUN}:order-processed__investigation:1`,
  session_id: `run:${SCENARIO_RUN}`,
  kind: "human_gate",
  project: "demo",
  gate_kind: "investigation",
  path: null,
  rule: null,
});

const catalog = aScenarioCatalog({
  items: [
    aScenarioSummary({ last_run: aScenarioRunRef() }),
    aScenarioSummary({
      name: "invoice-pdf",
      description: "An invoice gets its PDF",
      node_count: 4,
      last_run: aScenarioRunRef({
        run_id: "9b0d1f37",
        status: "done",
        ended_at: "2026-10-21T17:03:00.000Z",
      }),
    }),
    aScenarioSummary({
      name: "refund-flow",
      pack: "payments",
      description: null,
      node_count: 6,
      last_run: aScenarioRunRef({ run_id: "01c2e4aa", status: "cancelled" }),
    }),
    aScenarioSummary({
      name: "stock-sync",
      pack: "payments",
      description: "Stock counts match after a sync",
      node_count: 3,
    }),
  ],
  problems: [
    {
      ...aWorkflowProblem(),
      project: "demo",
      file: "scenarios/orders/returns.yaml",
      line: 14,
      key: "nodes[2].type",
      message: "shell nodes are not allowed in a scenario",
    },
  ],
});

const routes: ApiRoutes = {
  "/api/v1/scenarios": catalog,
  "/api/v1/approvals": aPage([waitingGate]),
  "/api/v1/workflow-runs": aPage([
    aRun({ id: SCENARIO_RUN, workflow: "scenario:order-lifecycle", project: "demo" }),
  ]),
};

function renderList(extra: ApiRoutes = {}, path = "/scenarios") {
  return renderWithApi(<ScenariosScreen />, { routes: { ...routes, ...extra }, path });
}

describe("ScenariosScreen (scenarios list)", () => {
  it("scenarios list renders each scenario with its pack, steps and last scenario run", async () => {
    renderList();

    const table = await screen.findByRole("table", { name: "Scenarios" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(5);
    expect(within(table).getByRole("link", { name: "order-lifecycle" })).toHaveAttribute(
      "href",
      "/scenarios/demo/order-lifecycle",
    );
    expect(within(table).getByText("One order from fetch to an active cover")).toBeInTheDocument();
    expect(within(table).getByText("No description.")).toBeInTheDocument();
    expect(within(table).getByText("Never run")).toBeInTheDocument();
    expect(within(table).getByText("Done")).toBeInTheDocument();
    expect(within(table).getByText("Cancelled")).toBeInTheDocument();
    expect(within(table).getByRole("link", { name: "Open scenario run 9b0d1f37" })).toHaveAttribute(
      "href",
      "/scenarios/demo/invoice-pdf/runs/9b0d1f37",
    );
    expect(
      screen.getByText("4 scenarios in 2 packs · 1 scenario run waits for you"),
    ).toBeInTheDocument();
    const problems = screen.getByRole("table", { name: "Files that do not load (1)" });
    expect(within(problems).getByText("scenarios/orders/returns.yaml:14")).toBeInTheDocument();
    expect(
      within(problems).getByText("shell nodes are not allowed in a scenario"),
    ).toBeInTheDocument();
  });

  it("scenarios list shows the waiting card for a scenario run paused at an investigation", async () => {
    renderList();

    const card = await screen.findByRole("region", { name: "Waiting for you" });
    expect(card).toHaveTextContent(
      `order-lifecycle · scenario run ${SCENARIO_RUN} paused at order-processed since`,
    );
    expect(
      within(card).getByRole("link", { name: `Open scenario run ${SCENARIO_RUN}` }),
    ).toHaveAttribute("href", `/scenarios/demo/order-lifecycle/runs/${SCENARIO_RUN}`);
    const table = screen.getByRole("table", { name: "Scenarios" });
    expect(within(table).getByText("Waiting for you")).toBeInTheDocument();
  });

  it("scenarios list says a policy ask waits for your approval at its step", async () => {
    renderList({
      "/api/v1/approvals": aPage([
        {
          ...waitingGate,
          id: `${SCENARIO_RUN}:fetch-order__ask:1`,
          gate_id: `${SCENARIO_RUN}:fetch-order__ask:1`,
          gate_kind: "policy",
        },
      ]),
    });

    const card = await screen.findByRole("region", { name: "Waiting for you" });
    expect(card).toHaveTextContent("waits for your approval at fetch-order since");
  });

  it("scenarios list shows the empty state", async () => {
    renderList({
      "/api/v1/scenarios": aScenarioCatalog({ items: [], problems: [] }),
      "/api/v1/approvals": aPage([]),
    });

    expect(await screen.findByText("No scenarios yet.")).toBeInTheDocument();
    expect(
      screen.getByText(/Scenarios are YAML files in the hub's scenarios\/<pack>\/ folder/),
    ).toBeInTheDocument();
    expect(screen.getByText("./hub scenario list")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Waiting for you" })).toBeNull();
  });

  it("scenarios list opens New scenario from its header and from its empty state", async () => {
    const user = userEvent.setup();
    const listed = renderList();
    await user.click(await screen.findByRole("button", { name: "New scenario" }));
    expect(listed.router.state.location.pathname).toBe("/scenarios/new");
    listed.unmount();

    const empty = renderList({
      "/api/v1/scenarios": aScenarioCatalog({ items: [], problems: [] }),
      "/api/v1/approvals": aPage([]),
    });
    await screen.findByText("No scenarios yet.");
    const buttons = screen.getAllByRole("button", { name: "New scenario" });
    expect(buttons).toHaveLength(2);
    await user.click(buttons[1] as HTMLElement);
    expect(empty.router.state.location.pathname).toBe("/scenarios/new");
  });

  it("scenarios list names the project in scope when it holds none", async () => {
    renderList(
      {
        "/api/v1/scenarios": aScenarioCatalog({ items: [], problems: [] }),
        "/api/v1/approvals": aPage([]),
      },
      "/scenarios?scope=demo",
    );

    expect(await screen.findByText("No scenarios in demo yet.")).toBeInTheDocument();
  });

  it("scenarios list filters by name or description and clears the filter", async () => {
    const user = userEvent.setup();
    const { router } = renderList();
    const filter = await screen.findByRole("searchbox", {
      name: "Filter scenarios by name or description",
    });

    await user.type(filter, "pdf");
    expect(router.state.location.search).toBe("?q=pdf");
    const table = screen.getByRole("table", { name: "Scenarios" });
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    await user.clear(filter);
    await user.type(filter, "refnd");
    expect(screen.getByText(/No scenarios match "refnd"\./)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filter" }));
    expect(router.state.location.search).toBe("");
    await user.keyboard("/");
    expect(filter).toHaveFocus();
  });

  describe("states", () => {
    it("scenarios list states: shows a skeleton after 300 ms while loading", () => {
      vi.useFakeTimers();
      try {
        const { container } = renderList({ "/api/v1/scenarios": "pending" });
        expect(container.querySelector('[aria-busy="true"]')).toBeNull();
        act(() => {
          vi.advanceTimersByTime(1100);
        });
        expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
        expect(screen.getByText("Loading scenarios")).toBeInTheDocument();
      } finally {
        vi.useRealTimers();
      }
    });

    it("scenarios list states: only files that do not load", async () => {
      renderList({
        "/api/v1/scenarios": aScenarioCatalog({ items: [], problems: catalog.problems }),
      });

      expect(await screen.findByText("No scenario loads.")).toBeInTheDocument();
      expect(screen.getByRole("table", { name: "Files that do not load (1)" })).toBeInTheDocument();
    });

    it("scenarios list states: a problem with Try again", async () => {
      renderList({
        "/api/v1/scenarios": aProblem({
          status: 409,
          title: "Conflict",
          detail: "The hub registry cannot be read.",
        }),
      });

      expect(await screen.findByText("Could not load scenarios")).toBeInTheDocument();
      expect(screen.getByText("The hub registry cannot be read.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    });

    it("scenarios list states: no waiting card when the open gates cannot be read", async () => {
      renderList({ "/api/v1/approvals": aProblem({ status: 500 }) });

      const table = await screen.findByRole("table", { name: "Scenarios" });
      expect(screen.queryByRole("region", { name: "Waiting for you" })).toBeNull();
      expect(within(table).getByText("Running")).toBeInTheDocument();
    });

    it("scenarios list states: stamps the header as stale when the collector is offline", async () => {
      renderList();

      await screen.findByRole("table", { name: "Scenarios" });
      expect(screen.getByText(/^Stale · as of/)).toBeInTheDocument();
    });
  });

  it("scenarios list has no serious a11y violation (a11y)", async () => {
    const { container } = renderList();

    await screen.findByRole("region", { name: "Waiting for you" });
    expect(await seriousViolations(container)).toEqual([]);
  });
  it("scenarios list heads the files that do not load and draws no colored card border", async () => {
    renderList();

    expect(
      await screen.findByRole("heading", { name: "Files that do not load (1)" }),
    ).toBeInTheDocument();
    const card = screen.getByRole("region", { name: "Waiting for you" });
    expect(card.style.borderLeft).toBe("");
  });
});
