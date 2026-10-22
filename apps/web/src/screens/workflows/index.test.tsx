import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aPage,
  aProblem,
  aWorkflowCatalog,
  aWorkflowDetail,
  aWorkflowSummary,
  anItemVersion,
  anItemVersionPage,
  aSkillCatalog,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { WorkflowDetailScreen, WorkflowsScreen } from ".";
import { SkillsScreen } from "../skills";

const DETAIL = "/api/v1/workflows/agent-hub/feature-flow";

/** The Toolkit of agent-hub on its Workflows tab, where the workflows list lives. */
function renderList(routes: ApiRoutes = { "/api/v1/workflows": aWorkflowCatalog() }, path = "") {
  return renderWithApi(<SkillsScreen />, {
    routes: { "/api/v1/projects/agent-hub/skills": aSkillCatalog(), ...routes },
    path: `/projects/agent-hub/skills?view=workflows${path}`,
    route: "projects/:project/skills",
  });
}

function renderDetail(reply: ApiRoutes[string] = aWorkflowDetail(), query = "") {
  return renderWithApi(<WorkflowDetailScreen />, {
    routes: { [DETAIL]: reply },
    path: `/workflows/agent-hub/feature-flow${query}`,
    route: "/workflows/:project/:name",
  });
}

describe("Toolkit › Workflows tab", () => {
  it("AC-427.10 lists the hub's workflows before the built-ins as catalog cards, each with its inputs and shape", async () => {
    renderList({
      "/api/v1/workflows": aWorkflowCatalog({
        items: [aWorkflowSummary({ name: "review", source: "builtin" }), aWorkflowSummary()],
      }),
    });

    const list = await screen.findByRole("list", { name: "Workflows" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("feature-flow");
    expect(rows[0]).toHaveTextContent("You give it: feature");
    expect(rows[0]).toHaveTextContent("4 steps · Claude does 1 · stops to ask you");
    expect(rows[0]).toHaveTextContent("Hub");
    expect(rows[1]).toHaveTextContent("review");
    expect(rows[1]).toHaveTextContent("Built-in");
  });

  it("AC-427.10 gives each card one Tab stop, its name", async () => {
    renderList({ "/api/v1/workflows": aWorkflowCatalog({ problems: [] }) });

    const list = await screen.findByRole("list", { name: "Workflows" });
    const card = within(list).getByRole("article", { name: "feature-flow" });
    expect(
      within(card)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["feature-flow"]);
    expect(within(card).queryByRole("button")).toBeNull();
  });

  it("says in one sentence what a workflow is, and selects its tab", async () => {
    renderList();

    expect(await screen.findByText(/Jobs the hub runs from start to finish/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^Workflows/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("lists the files that do not load with their line and key", async () => {
    renderList();

    const problems = await screen.findByRole("table", { name: "Files that do not load" });
    expect(problems).toHaveTextContent("workflows/team/broken.yaml:12");
    expect(problems).toHaveTextContent("nodes[1].depends_on");
    expect(problems).toHaveTextContent("depends on unknown node 'plan'");
  });

  it("asks the API for the project of the Toolkit", async () => {
    const { requests } = renderList();

    await screen.findByRole("list", { name: "Workflows" });
    expect(requests.some((r) => r.url.includes("project=agent-hub"))).toBe(true);
  });

  it("opens a workflow's detail from its name", async () => {
    const user = userEvent.setup();
    const { router } = renderList();

    await user.click(await screen.findByRole("link", { name: /^feature-flow/ }));

    expect(router.state.location.pathname).toBe(
      "/projects/agent-hub/skills/workflows/feature-flow",
    );
  });

  it("says how to add one when no workflow and no problem exist", async () => {
    renderList({ "/api/v1/workflows": aWorkflowCatalog({ items: [], problems: [] }) });

    expect(await screen.findByText("No workflows defined")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Files that do not load" })).toBeNull();
  });

  it("shows the problem when the catalog cannot be read", async () => {
    renderList({ "/api/v1/workflows": aProblem({ status: 500, detail: "boom" }) });

    expect(await screen.findByText("Could not load workflows")).toBeInTheDocument();
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = renderList();

    await screen.findByRole("table", { name: "Files that do not load" });
    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("WorkflowsScreen", () => {
  it("sends /workflows to the Toolkit picker with All projects in scope", () => {
    const { router } = renderWithApi(<WorkflowsScreen />, { path: "/workflows" });

    expect(router.state.location.pathname).toBe("/knowledge/skills");
  });

  it("sends /workflows to the Workflows tab of the project in scope's Toolkit", () => {
    const { router } = renderWithApi(<WorkflowsScreen />, {
      path: "/workflows?scope=agent-hub",
      route: "/workflows",
    });

    expect(router.state.location.pathname).toBe("/projects/agent-hub/skills");
    expect(router.state.location.search).toBe("?view=workflows");
  });
});

describe("WorkflowDetailScreen in the Toolkit", () => {
  it("places the workflow under its project's Toolkit and Workflows tab", async () => {
    renderWithApi(<WorkflowDetailScreen />, {
      routes: { [DETAIL]: aWorkflowDetail() },
      path: "/projects/agent-hub/skills/workflows/feature-flow",
      route: "projects/:project/skills/workflows/:name",
    });

    const crumbs = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(
      within(crumbs)
        .getAllByRole("link")
        .map((link) => [link.textContent, link.getAttribute("href")]),
    ).toEqual([
      ["Portfolio", "/"],
      ["agent-hub", "/projects/agent-hub"],
      ["Toolkit", "/projects/agent-hub/skills"],
      ["Workflows", "/projects/agent-hub/skills?view=workflows"],
    ]);
    expect(within(crumbs).getByText("feature-flow")).toHaveAttribute("aria-current", "page");
  });
});

describe("WorkflowDetailScreen history", () => {
  it("history_panel on a hub workflow and none on a builtin", async () => {
    const user = userEvent.setup();
    const { unmount } = renderWithApi(<WorkflowDetailScreen />, {
      routes: {
        [DETAIL]: aWorkflowDetail(),
        [`${DETAIL}/versions`]: anItemVersionPage({
          unit_kind: "workflow",
          unit_path: "workflows/team/feature-flow.yaml",
          items: [anItemVersion({ origin: "external", author: null })],
        }),
      },
      path: "/workflows/agent-hub/feature-flow?view=document",
      route: "/workflows/:project/:name",
    });

    const panel = await screen.findByRole("region", { name: "History" });
    await user.click(within(panel).getByRole("button", { name: "Show history" }));
    const table = await within(panel).findByRole("table", { name: "Versions of feature-flow" });
    expect(table).toHaveTextContent("Changed outside the app");
    unmount();

    renderDetail(aWorkflowDetail({ source: "builtin" }), "?view=document");
    await screen.findByRole("region", { name: "Document" });
    expect(screen.queryByRole("region", { name: "History" })).toBeNull();
  });
});

describe("WorkflowDetailScreen", () => {
  it("draws one column per layer with a node per declared node and its type", async () => {
    renderDetail();

    const graph = await screen.findByRole("group", { name: "Workflow graph" });
    const layers = within(graph).getAllByRole("list");
    expect(layers.map((layer) => layer.getAttribute("aria-label"))).toEqual([
      "Layer 1",
      "Layer 2",
      "Layer 3",
    ]);
    const second = layers[1];
    if (!second) throw new Error("No layer 2");
    expect(within(second).getAllByRole("button")).toHaveLength(2);
    expect(
      within(graph).getByRole("button", { name: /review.*Approval by you/ }),
    ).toBeInTheDocument();
  });

  it("draws an edge for each depends_on", async () => {
    const { container } = renderDetail();

    await screen.findByRole("group", { name: "Workflow graph" });
    const edges = [...container.querySelectorAll("[data-edge]")].map((e) =>
      e.getAttribute("data-edge"),
    );
    expect(edges.sort()).toEqual(["build→review", "docs→review", "plan→build", "plan→docs"]);
  });

  it("AC-427.9 opens the node panel from the keyboard and returns focus on close", async () => {
    const user = userEvent.setup();
    const { router } = renderDetail();

    const build = await screen.findByRole("button", { name: /build.*Command/ });
    build.focus();
    await user.keyboard("{Enter}");

    const panel = await screen.findByRole("complementary", { name: "Node build" });
    expect(panel).toHaveTextContent("Waits forplan");
    expect(panel).toHaveTextContent("Leads toreview");
    expect(within(panel).getByRole("group", { name: "Command of build" })).toHaveTextContent(
      "make check",
    );
    expect(router.state.location.search).toContain("node=build");
    await waitFor(() => {
      expect(panel).toContainElement(document.activeElement as HTMLElement);
    });

    await user.click(within(panel).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("complementary", { name: "Node build" })).toBeNull();
    expect(screen.getByRole("button", { name: /build.*Command/ })).toHaveFocus();
  });

  it("offers the Steps view as the graph's text alternative, from the view switch", async () => {
    const user = userEvent.setup();
    const { router } = renderDetail();

    await screen.findByRole("group", { name: "Workflow graph" });
    expect(screen.queryByRole("list", { name: "Steps" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Steps" }));

    expect(screen.getByRole("list", { name: "Steps" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Workflow graph" })).toBeNull();
    expect(router.state.location.search).toContain("view=steps");
  });

  it("AC-427.3 lists the steps in run order in plain words, and what a run takes", async () => {
    renderDetail(aWorkflowDetail(), "?view=steps");

    const steps = await screen.findByRole("list", { name: "Steps" });
    const items = within(steps).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringMatching(/^1Step 1: .*AI agent.*plan/),
      expect.stringMatching(/^2Step 2: build.*Command/),
      expect.stringMatching(/^3Step 3: .*Command.*docs/),
      expect.stringMatching(/^4Step 4: review.*Approval by you/),
    ]);
    expect(items[0]).toHaveTextContent("Writes the plan.");
    expect(items[2]).toHaveTextContent("Waits for plan");
    const inputs = screen.getByRole("region", { name: "What you give it" });
    expect(inputs).toHaveTextContent("feature");
    expect(inputs).toHaveTextContent("What to build.");
  });

  it("shows the document read-only", async () => {
    renderDetail(aWorkflowDetail(), "?view=document");

    const doc = await screen.findByRole("region", { name: "Document" });
    expect(doc).toHaveTextContent('"name": "feature-flow"');
    expect(within(doc).queryByRole("textbox")).toBeNull();
  });

  it("says the workflow is not found on a 404", async () => {
    renderDetail(aProblem({ status: 404, title: "Not found" }));

    expect(
      await screen.findByRole("heading", { name: "Workflow feature-flow not found" }),
    ).toBeInTheDocument();
  });

  it("draws edges in world coordinates when the canvas is zoomed", async () => {
    // The world is drawn at 50%: 1200 px wide, 600 px on screen. World x of each node, 168 x 40.
    const worldX: Record<string, number> = { plan: 4, build: 220, docs: 220, review: 436 };
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1200);
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (
      this: Element,
    ) {
      const id = this.getAttribute("data-node-id");
      const x = id === null ? undefined : worldX[id];
      if (x === undefined) return new DOMRect(100, 50, 600, 300);
      const top = id === "docs" ? 104 : 54;
      return new DOMRect(100 + x / 2, top, 84, 20);
    });
    const { container } = renderDetail();

    await screen.findByRole("group", { name: "Workflow graph" });
    await waitFor(() => {
      expect(container.querySelector('[data-edge="plan→docs"]')).toHaveAttribute(
        "d",
        "M 172 28 C 196 28, 196 128, 220 128",
      );
    });
  });

  it("observes each node so a node that reflows redraws the edges", async () => {
    const observed: Element[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe = (el: Element) => observed.push(el);
        disconnect = vi.fn();
      },
    );
    renderDetail();

    await screen.findByRole("group", { name: "Workflow graph" });
    const ids = observed
      .map((el) => el.getAttribute("data-node-id") ?? "")
      .filter((id) => id !== "" && !id.startsWith("row:"));
    expect(ids.sort()).toEqual(["build", "docs", "plan", "review"]);
  });

  it("gives focus to the node when nothing held focus as the panel opened", async () => {
    const user = userEvent.setup();
    renderDetail();

    // A mouse click in Safari leaves focus on the body.
    const docs = await screen.findByRole("button", { name: /docs.*Command/ });
    expect(document.activeElement).toBe(document.body);
    fireEvent.click(docs);
    const panel = await screen.findByRole("complementary", { name: "Node docs" });
    await user.click(within(panel).getByRole("button", { name: "Close" }));
    expect(screen.getByRole("button", { name: /docs.*Command/ })).toHaveFocus();
  });

  it("leaves focus alone when a node is opened by the URL", async () => {
    renderDetail(aWorkflowDetail(), "?node=plan");

    const panel = await screen.findByRole("complementary", { name: "Node plan" });
    expect(panel).not.toContainElement(document.activeElement as HTMLElement);
  });

  it("has no serious a11y violations with a node open (a11y)", async () => {
    const { container } = renderDetail(aWorkflowDetail(), "?node=plan");

    await screen.findByRole("complementary", { name: "Node plan" });
    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("WorkflowDetailScreen, starting and reading (AC-PG-13)", () => {
  function renderWith(name: string, detail: ApiRoutes[string], query = "") {
    return renderWithApi(<WorkflowDetailScreen />, {
      routes: {
        [`/api/v1/workflows/agent-hub/${name}`]: detail,
        "/api/v1/workflows": aWorkflowCatalog({ problems: [] }),
        "/api/v1/workflow-runs": aPage([]),
      },
      path: `/workflows/agent-hub/${name}${query}`,
      route: "/workflows/:project/:name",
    });
  }

  it("AC-PG-13.3 opens Start run with this workflow chosen from Run this workflow", async () => {
    const user = userEvent.setup();
    renderWith("feature-flow", aWorkflowDetail());

    await user.click(await screen.findByRole("button", { name: "Run this workflow" }));

    const dialog = screen.getByRole("dialog", { name: "Start a workflow run" });
    const picker = within(dialog).getByRole("combobox", { name: "Workflow" });
    await waitFor(() => {
      expect(picker).toHaveDisplayValue("agent-hub / feature-flow");
    });
  });

  it("AC-PG-13.3 offers no start from the page for issue-to-pr, which starts from hub run", async () => {
    renderWith("issue-to-pr", aWorkflowDetail({ name: "issue-to-pr", source: "builtin" }));

    await screen.findByRole("heading", { level: 1, name: "issue-to-pr" });
    expect(screen.queryByRole("button", { name: "Run this workflow" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Start run" })).toBeNull();
    expect(screen.getByText(/Starts from/)).toHaveTextContent("Starts from hub run");
  });

  it("AC-PG-13.4 opens on the graph, with the steps and the document one view away", async () => {
    const user = userEvent.setup();
    renderWith("feature-flow", aWorkflowDetail());

    const switcher = await screen.findByRole("group", { name: "View" });
    expect(within(switcher).getByRole("button", { name: "Graph" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("group", { name: "Workflow graph" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Document" })).toBeNull();
    await user.click(within(switcher).getByRole("button", { name: "Document" }));
    expect(screen.getByRole("region", { name: "Document" })).toBeInTheDocument();
  });

  it("AC-PG-13.4 links a step of the Steps view to the same step in the graph", async () => {
    const user = userEvent.setup();
    const { router } = renderWith("feature-flow", aWorkflowDetail(), "?view=steps");

    await user.click(await screen.findByRole("link", { name: "Show plan in the graph" }));

    expect(router.state.location.search).toContain("view=graph");
    expect(router.state.location.search).toContain("node=plan");
    expect(await screen.findByRole("complementary", { name: "Node plan" })).toBeInTheDocument();
  });

  it("AC-PG-13.4 AC-427.5 AC-427.6 shows each step's kind, its prompt or command, and a repeat's rounds", async () => {
    renderWith(
      "feature-flow",
      aWorkflowDetail({
        layers: [[{ id: "fixing", type: "loop_group", depends_on: [], description: null }]],
        document: {
          name: "feature-flow",
          nodes: [
            {
              id: "fixing",
              type: "loop_group",
              max_iterations: 3,
              until_bash: ["make", "check"],
              nodes: [
                { id: "fixing__fix", type: "agent", prompt: "Fix the failing test." },
                {
                  id: "fixing__check",
                  type: "shell",
                  depends_on: ["fixing__fix"],
                  command: ["make", "check"],
                },
              ],
            },
          ],
        },
      }),
      "?view=steps",
    );

    const steps = await screen.findByRole("list", { name: "Steps" });
    expect(steps).toHaveTextContent("Rounds, up to 3");
    expect(steps).toHaveTextContent("Stops when make check passes.");
    expect(steps).toHaveTextContent("If round 3 ends without stopping, this step fails.");
    expect(within(steps).getByText("Read the prompt")).toBeInTheDocument();
    expect(steps).toHaveTextContent("Fix the failing test.");
    expect(within(steps).getByRole("group", { name: "Command of check" })).toHaveTextContent(
      "make check",
    );
  });

  it("AC-427.4 shows a step's condition as text, not only in a tooltip", async () => {
    renderWith(
      "feature-flow",
      aWorkflowDetail({
        layers: [[{ id: "docs", type: "shell", depends_on: [], description: "Builds the docs." }]],
        document: {
          name: "feature-flow",
          nodes: [
            {
              id: "docs",
              type: "shell",
              description: "Builds the docs.",
              when: "$check.output.passed == true",
              command: ["make", "docs"],
            },
          ],
        },
      }),
      "?view=steps",
    );

    const steps = await screen.findByRole("list", { name: "Steps" });
    expect(steps).toHaveTextContent("Only when $check.output.passed == true");
  });

  it("AC-427.7 moves across the steps with j and k", async () => {
    // jsdom has no scrollIntoView.
    Element.prototype.scrollIntoView = vi.fn();
    const user = userEvent.setup();
    renderWith("feature-flow", aWorkflowDetail(), "?view=steps");

    const steps = await screen.findByRole("list", { name: "Steps" });
    const items = within(steps).getAllByRole("listitem");
    await user.keyboard("j");
    expect(items[0]).toHaveFocus();
    await user.keyboard("j");
    expect(items[1]).toHaveFocus();
    await user.keyboard("k");
    expect(items[0]).toHaveFocus();
  });

  it("AC-427.11 has no serious a11y violations with rounds and an open prompt (a11y)", async () => {
    const user = userEvent.setup();
    const { container } = renderWith(
      "feature-flow",
      aWorkflowDetail({
        layers: [[{ id: "fixing", type: "loop_group", depends_on: [], description: null }]],
        document: {
          name: "feature-flow",
          nodes: [
            {
              id: "fixing",
              type: "loop_group",
              max_iterations: 3,
              until_when: "$check.output.passed == true",
              nodes: [
                { id: "fixing__fix", type: "agent", prompt: "Fix it.", context: "fresh" },
                {
                  id: "fixing__check",
                  type: "shell",
                  when: "$fix.output.done == true",
                  command: ["make", "check"],
                },
              ],
            },
          ],
        },
      }),
      "?view=steps",
    );

    await user.click(await screen.findByText("Read the prompt"));
    expect(screen.getByText("Starts afresh each round")).toBeInTheDocument();
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("AC-427.1 holds the inputs, the revision and the runs link in the About rail", async () => {
    renderWith("feature-flow", aWorkflowDetail({ revision: 4 }));

    const rail = await screen.findByRole("complementary", { name: "About this workflow" });
    expect(within(rail).getByRole("region", { name: "What you give it" })).toHaveTextContent(
      "feature",
    );
    expect(within(rail).getByRole("region", { name: "Where it lives" })).toHaveTextContent(
      "Revisionr4",
    );
    expect(within(rail).getByRole("link", { name: "Runs of this workflow" })).toHaveAttribute(
      "href",
      "/runs?workflow=feature-flow",
    );
  });

  it("AC-427.2 says the shape in words under the description, a repeat in rounds", async () => {
    renderWith(
      "feature-flow",
      aWorkflowDetail({
        steps: [
          { id: "plan", type: "agent", max_iterations: null, body: [] },
          {
            id: "fixing",
            type: "loop_group",
            max_iterations: 3,
            body: [{ id: "fix", type: "agent", max_iterations: null, body: [] }],
          },
        ],
      }),
      "?view=steps",
    );

    expect(
      await screen.findByText(
        "2 steps · Claude does 2 · repeats in up to 3 rounds · runs without you",
      ),
    ).toBeInTheDocument();
    const heading = screen.getByRole("heading", { name: "Step by step" });
    expect(heading.parentElement).toHaveTextContent("1 AI agent");
  });

  it("AC-427.8 says a workflow without steps has none", async () => {
    renderWith("feature-flow", aWorkflowDetail({ layers: [], document: { name: "feature-flow" } }));

    expect(await screen.findByText("This workflow has no steps.")).toBeInTheDocument();
  });

  it("AC-427.8 shows a skeleton of the page while the workflow loads", async () => {
    renderWith("feature-flow", "pending");

    expect(
      await screen.findByRole("status", { name: "Loading feature-flow" }, { timeout: 2000 }),
    ).toHaveAttribute("aria-busy", "true");
  });

  it("AC-427.9 opens a chosen step in the canvas's panel, in place of About", async () => {
    renderWith("feature-flow", aWorkflowDetail(), "?node=review");

    const panel = await screen.findByRole("complementary", { name: "Node review" });
    expect(screen.queryByRole("complementary", { name: "About this workflow" })).toBeNull();
    expect(panel.closest(".wf-canvas")).toContainElement(
      screen.getByRole("group", { name: "Workflow graph" }),
    );
    expect(panel).toHaveTextContent("Approval by you");
    expect(panel).toHaveTextContent("Waits forbuilddocs");
    expect(panel).toHaveTextContent("Leads toEnds the run");
    expect(panel).toHaveTextContent("You are asked: “Ship it?”");
    expect(panel).toHaveTextContent("As written in the file");
  });

  it("AC-PG-13.4 says a built-in is not a hub file and how to propose a copy", async () => {
    renderWith("issue-to-pr", aWorkflowDetail({ name: "issue-to-pr", source: "builtin" }));

    const lives = await screen.findByRole("region", { name: "Where it lives" });
    expect(lives).toHaveTextContent("Built into agent-hub.");
    expect(lives).toHaveTextContent(
      "To change it, copy it into the hub's workflows/ folder with the same name: the hub's copy wins.",
    );
  });
});

describe("The workflow canvas", () => {
  const ROUNDS = aWorkflowDetail({
    layers: [
      [{ id: "plan", type: "agent", depends_on: [], description: null }],
      [{ id: "fixing", type: "loop_group", depends_on: ["plan"], description: "Fix until green." }],
    ],
    document: {
      name: "feature-flow",
      nodes: [
        { id: "plan", type: "agent" },
        {
          id: "fixing",
          type: "loop_group",
          depends_on: ["plan"],
          max_iterations: 3,
          until_bash: ["make", "check"],
          nodes: [
            { id: "fix", type: "agent", context: "fresh" },
            { id: "check", type: "shell", depends_on: ["fix"], when: "$fix.output.ok" },
          ],
        },
      ],
    },
  });

  it("AC-WG.5 is one Tab stop whose arrow keys follow the edges and columns, and j/k run order", async () => {
    const user = userEvent.setup();
    renderDetail();

    const graph = await screen.findByRole("group", { name: "Workflow graph" });
    const stops = within(graph)
      .getAllByRole("button")
      .filter((b) => b.tabIndex === 0);
    expect(stops.map((b) => b.id)).toEqual(["wf-node-plan"]);
    stops[0]?.focus();
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement?.id).toBe("wf-node-build");
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement?.id).toBe("wf-node-docs");
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement?.id).toBe("wf-node-review");
    await user.keyboard("{ArrowLeft}");
    expect(document.activeElement?.id).toBe("wf-node-build");
    await user.keyboard("k");
    expect(document.activeElement?.id).toBe("wf-node-plan");
  });

  it("AC-WG.5 closes the chosen step with Esc and gives focus back to it", async () => {
    const user = userEvent.setup();
    renderDetail();

    const build = await screen.findByRole("button", { name: /build.*Command/ });
    build.focus();
    await user.keyboard("{Enter}");
    await screen.findByRole("complementary", { name: "Node build" });
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("complementary", { name: "Node build" })).toBeNull();
    expect(screen.getByRole("button", { name: /build.*Command/ })).toHaveFocus();
    expect(screen.getByRole("complementary", { name: "About this workflow" })).toBeInTheDocument();
  });

  it("AC-WG.2 lights the chosen step's own edges and fades the edges off its chain", async () => {
    const { container } = renderDetail(aWorkflowDetail(), "?node=build");

    await screen.findByRole("complementary", { name: "Node build" });
    const edge = (key: string) => container.querySelector(`[data-edge="${key}"]`);
    expect(edge("plan→build")).toHaveAttribute("data-hot");
    expect(edge("build→review")).toHaveAttribute("data-hot");
    expect(edge("plan→docs")).toHaveAttribute("data-dim");
    expect(edge("docs→review")).toHaveAttribute("data-dim");
    expect(screen.getByRole("button", { name: /build.*Command/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("AC-WG.3 draws a rounds group as a frame of its own steps, its rule in the head, and folds it", async () => {
    const user = userEvent.setup();
    const { container } = renderDetail(ROUNDS);

    const frame = await screen.findByRole("group", { name: "fixing rounds: up to 3" });
    expect(frame).toHaveTextContent("Fix until green.");
    expect(frame).toHaveTextContent("Up to 3 rounds · Stops when make check passes");
    expect(within(frame).getByRole("list", { name: "Layer 2 of fixing" })).toHaveTextContent(
      "check",
    );
    expect(within(frame).getByRole("button", { name: /check.*Only when/ })).toBeInTheDocument();
    expect(within(frame).getByRole("button", { name: /fix.*Starts afresh/ })).toBeInTheDocument();
    expect(container.querySelector('[data-edge="fixing__fix→fixing__check"]')).not.toBeNull();

    await user.click(within(frame).getByRole("button", { name: "Collapse rounds" }));

    expect(frame).toHaveTextContent("2 steps inside");
    expect(within(frame).queryByRole("list")).toBeNull();
    expect(container.querySelector('[data-edge="fixing__fix→fixing__check"]')).toBeNull();
    expect(within(frame).getByRole("button", { name: "Expand rounds" })).toBeInTheDocument();
  });

  it("AC-WG.3 closes a rounds frame with left and opens it with right, from the keyboard", async () => {
    const user = userEvent.setup();
    renderDetail(ROUNDS);

    const frame = await screen.findByRole("group", { name: "fixing rounds: up to 3" });
    document.getElementById("wf-node-fixing")?.focus();
    await user.keyboard("{ArrowLeft}");
    expect(frame).toHaveTextContent("2 steps inside");
    expect(document.activeElement?.id).toBe("wf-node-fixing");
    await user.keyboard("{ArrowRight}");
    expect(within(frame).getByRole("list", { name: "Layer 1 of fixing" })).toBeInTheDocument();
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement?.id).toBe("wf-node-fixing__fix");
  });

  it("AC-WG.3 shows a group's rule and its own steps in the panel, and opens one from there", async () => {
    const user = userEvent.setup();
    renderDetail(ROUNDS, "?node=fixing");

    const panel = await screen.findByRole("complementary", { name: "Node fixing" });
    expect(panel).toHaveTextContent("Stops when make check passes.");
    expect(panel).toHaveTextContent("If round 3 ends without stopping, this step fails.");
    await user.click(within(panel).getByRole("button", { name: "check" }));

    const step = await screen.findByRole("complementary", { name: "Node fixing__check" });
    expect(step).toHaveTextContent("Only when$fix.output.ok");
    expect(step).toHaveTextContent("Waits forfix");
  });

  it("AC-WG.4 zooms in and out from the controls and resets to 100%", async () => {
    const user = userEvent.setup();
    renderDetail();

    const controls = await screen.findByRole("toolbar", { name: "Graph view" });
    const reset = within(controls).getByRole("button", { name: "Reset zoom to 100%" });
    expect(reset).toHaveTextContent("100%");
    await user.click(within(controls).getByRole("button", { name: "Zoom in (+)" }));
    expect(reset).toHaveTextContent("120%");
    await user.click(within(controls).getByRole("button", { name: "Zoom out (−)" }));
    await user.click(within(controls).getByRole("button", { name: "Zoom out (−)" }));
    expect(reset).toHaveTextContent("83%");
    await user.click(reset);
    expect(reset).toHaveTextContent("100%");
    const world = screen.getByRole("group", { name: "Workflow graph" });
    expect(world.style.transform).toContain("scale(1)");
  });

  it("AC-WG.8 has no serious a11y violations with a group open and a step chosen (a11y)", async () => {
    const { container } = renderDetail(ROUNDS, "?node=fixing__fix");

    await screen.findByRole("complementary", { name: "Node fixing__fix" });
    expect(await seriousViolations(container)).toEqual([]);
  });
});
