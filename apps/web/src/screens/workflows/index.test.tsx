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
  it("lists the hub's workflows before the built-ins, each with its inputs and shape", async () => {
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
    expect(rows[1]).toHaveTextContent("reviewbuilt-in");
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
      path: "/workflows/agent-hub/feature-flow",
      route: "/workflows/:project/:name",
    });

    const panel = await screen.findByRole("region", { name: "History" });
    await user.click(within(panel).getByRole("button", { name: "Show history" }));
    const table = await within(panel).findByRole("table", { name: "Versions of feature-flow" });
    expect(table).toHaveTextContent("Changed outside the app");
    unmount();

    renderDetail(aWorkflowDetail({ source: "builtin" }));
    await screen.findByRole("group", { name: "Workflow graph" });
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
    expect(within(graph).getByRole("button", { name: /review.*approval/ })).toBeInTheDocument();
  });

  it("draws an edge for each depends_on", async () => {
    const { container } = renderDetail();

    await screen.findByRole("group", { name: "Workflow graph" });
    const edges = [...container.querySelectorAll("[data-edge]")].map((e) =>
      e.getAttribute("data-edge"),
    );
    expect(edges.sort()).toEqual(["build→review", "docs→review", "plan→build", "plan→docs"]);
  });

  it("opens the node panel from the keyboard and returns focus on close", async () => {
    const user = userEvent.setup();
    const { router } = renderDetail();

    const build = await screen.findByRole("button", { name: /build.*shell/ });
    build.focus();
    await user.keyboard("{Enter}");

    const panel = await screen.findByRole("complementary", { name: "Node build" });
    expect(panel).toHaveTextContent("Waits for");
    expect(panel).toHaveTextContent("plan");
    expect(panel).toHaveTextContent("make");
    expect(router.state.location.search).toContain("node=build");
    await waitFor(() => {
      expect(panel).toContainElement(document.activeElement as HTMLElement);
    });

    await user.click(within(panel).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("complementary", { name: "Node build" })).toBeNull();
    expect(screen.getByRole("button", { name: /build.*shell/ })).toHaveFocus();
  });

  it("offers a list view as the graph's text alternative", async () => {
    const user = userEvent.setup();
    renderDetail();

    await user.click(await screen.findByRole("button", { name: "List" }));

    const table = screen.getByRole("table", { name: "Nodes in run order" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual([
      "1planagent—",
      "2buildshellplan",
      "2docsscriptplan",
      "3reviewapprovalbuild, docs",
    ]);
  });

  it("lists the steps in run order in plain words, and what a run takes", async () => {
    renderDetail();

    const steps = await screen.findByRole("list", { name: "Steps" });
    const items = within(steps).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining("AI agentplan"),
      expect.stringContaining("Commandbuild"),
      expect.stringContaining("Commanddocs"),
      expect.stringContaining("Approval by youreview"),
    ]);
    expect(items[0]).toHaveTextContent("Writes the plan.");
    expect(items[2]).toHaveTextContent("after plan");
    const inputs = screen.getByRole("region", { name: "What you give it" });
    expect(inputs).toHaveTextContent("feature");
    expect(inputs).toHaveTextContent("What to build.");
  });

  it("shows the document read-only", async () => {
    renderDetail();

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

  it("draws edges in content coordinates when the graph is scrolled sideways", async () => {
    // Content x of each node (all at top 4, 40 high); the graph is scrolled 400 px right.
    const contentX: Record<string, number> = { plan: 4, build: 220, docs: 220, review: 436 };
    const scrollLeft = 400;
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (
      this: Element,
    ) {
      const id = this.getAttribute("data-node-id");
      const x = id === null ? undefined : contentX[id];
      if (x === undefined) return new DOMRect(100, 50, 600, 300);
      const top = id === "docs" ? 104 : 54;
      return new DOMRect(100 + x - scrollLeft, top, 168, 40);
    });
    vi.spyOn(Element.prototype, "scrollLeft", "get").mockReturnValue(scrollLeft);
    vi.spyOn(Element.prototype, "scrollTop", "get").mockReturnValue(0);
    vi.spyOn(Element.prototype, "scrollWidth", "get").mockReturnValue(1200);
    vi.spyOn(Element.prototype, "scrollHeight", "get").mockReturnValue(300);
    const { container } = renderDetail();

    await screen.findByRole("group", { name: "Workflow graph" });
    await waitFor(() => {
      expect(container.querySelector('[data-edge="plan→docs"]')).toHaveAttribute(
        "d",
        "M 172 24 C 196 24, 196 74, 220 74",
      );
    });
    const svg = container.querySelector("svg[data-edges]");
    expect(svg).toHaveAttribute("width", "1200");
    expect(svg).toHaveAttribute("height", "300");
  });

  it("gives focus back to the list row that opened the panel", async () => {
    const user = userEvent.setup();
    renderDetail();

    await user.click(await screen.findByRole("button", { name: "List" }));
    const table = screen.getByRole("table", { name: "Nodes in run order" });
    const row = within(table).getByText("docs").closest("tr");
    if (!row) throw new Error("No docs row");
    row.focus();
    await user.keyboard("{Enter}");

    const panel = await screen.findByRole("complementary", { name: "Node docs" });
    await user.click(within(panel).getByRole("button", { name: "Close" }));
    expect(row).toHaveFocus();
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
    const ids = observed.map((el) => el.getAttribute("data-node-id")).filter(Boolean);
    expect(ids.sort()).toEqual(["build", "docs", "plan", "review"]);
  });

  it("gives focus to the node when nothing held focus as the panel opened", async () => {
    const user = userEvent.setup();
    renderDetail();

    // A mouse click in Safari leaves focus on the body.
    const docs = await screen.findByRole("button", { name: /docs.*script/ });
    expect(document.activeElement).toBe(document.body);
    fireEvent.click(docs);
    const panel = await screen.findByRole("complementary", { name: "Node docs" });
    await user.click(within(panel).getByRole("button", { name: "Close" }));
    expect(screen.getByRole("button", { name: /docs.*script/ })).toHaveFocus();
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

  it("AC-PG-13.4 keeps the graph and document in a closed Advanced disclosure", async () => {
    renderWith("feature-flow", aWorkflowDetail());

    const summary = await screen.findByText("Advanced: graph and document");
    const details = summary.closest("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");
    expect(details).toContainElement(screen.getByRole("group", { name: "Workflow graph" }));
    expect(details).toContainElement(screen.getByRole("region", { name: "Document" }));
    expect(details).not.toContainElement(screen.getByRole("list", { name: "Steps" }));
  });

  it("AC-PG-13.4 opens the Advanced disclosure when a step is selected", async () => {
    renderWith("feature-flow", aWorkflowDetail(), "?node=plan");

    await screen.findByRole("complementary", { name: "Node plan" });
    expect(screen.getByText("Advanced: graph and document").closest("details")).toHaveAttribute(
      "open",
    );
  });

  it("AC-PG-13.4 shows each step's kind, its prompt or command, and a repeat's rounds", async () => {
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
    );

    const steps = await screen.findByRole("list", { name: "Steps" });
    expect(steps).toHaveTextContent(
      "Each round runs these steps; at most 3 rounds, stopping as soon as they pass.",
    );
    expect(within(steps).getByText("Read the prompt")).toBeInTheDocument();
    expect(steps).toHaveTextContent("Fix the failing test.");
    expect(steps).toHaveTextContent("$ make check");
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
