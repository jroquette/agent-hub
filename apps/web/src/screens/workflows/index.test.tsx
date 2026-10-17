import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aProblem,
  aWorkflowCatalog,
  aWorkflowDetail,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { WorkflowDetailScreen, WorkflowsScreen } from ".";

const DETAIL = "/api/v1/workflows/agent-hub/feature-flow";

function renderList(routes: ApiRoutes = { "/api/v1/workflows": aWorkflowCatalog() }, path = "") {
  return renderWithApi(<WorkflowsScreen />, { routes, path: `/workflows${path}` });
}

function renderDetail(reply: ApiRoutes[string] = aWorkflowDetail(), query = "") {
  return renderWithApi(<WorkflowDetailScreen />, {
    routes: { [DETAIL]: reply },
    path: `/workflows/agent-hub/feature-flow${query}`,
    route: "/workflows/:project/:name",
  });
}

describe("WorkflowsScreen", () => {
  it("lists each workflow as a card with its source, step kinds and inputs", async () => {
    renderList();

    await screen.findByText("issue-to-pr");
    const list = screen.getByRole("list", { name: "Workflows" });
    const cards = within(list).getAllByRole("listitem");
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent("feature-flow");
    expect(cards[0]).toHaveTextContent("Hub");
    expect(cards[0]).toHaveTextContent("1 AI agent");
    expect(cards[0]).toHaveTextContent("2 commands");
    expect(cards[0]).toHaveTextContent("1 approval by you");
    expect(cards[0]).toHaveTextContent("You give it:feature");
    expect(cards[1]).toHaveTextContent("issue-to-pr");
    expect(cards[1]).toHaveTextContent("Built-in");
  });

  it("explains what a workflow is and its kinds of step", async () => {
    renderList();

    const intro = await screen.findByRole("region", { name: "What is a workflow" });
    expect(intro).toHaveTextContent("recipe the hub follows on its own");
    expect(within(intro).getAllByRole("listitem")).toHaveLength(4);
  });

  it("lists the files that do not load with their line and key", async () => {
    renderList();

    const problems = await screen.findByRole("table", { name: "Files that do not load" });
    expect(problems).toHaveTextContent("workflows/team/broken.yaml:12");
    expect(problems).toHaveTextContent("nodes[1].depends_on");
    expect(problems).toHaveTextContent("depends on unknown node 'plan'");
  });

  it("asks the API for the project in scope", async () => {
    const { requests } = renderList(undefined, "?scope=agent-hub");

    await screen.findByRole("list", { name: "Workflows" });
    expect(requests.some((r) => r.url.includes("project=agent-hub"))).toBe(true);
  });

  it("opens a workflow's detail when its card is chosen", async () => {
    const user = userEvent.setup();
    const { router } = renderList();

    await user.click(await screen.findByText("feature-flow"));

    expect(router.state.location.pathname).toBe("/workflows/agent-hub/feature-flow");
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
