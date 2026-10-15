import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

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
  it("lists each workflow with its source, revision and size", async () => {
    renderList();

    await screen.findByText("issue-to-pr");
    const table = screen.getByRole("table", { name: "Workflows" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("feature-flow");
    expect(rows[0]).toHaveTextContent("Hub");
    expect(rows[0]).toHaveTextContent("r3");
    expect(rows[0]).toHaveTextContent("4 nodes · 3 layers");
    expect(rows[1]).toHaveTextContent("issue-to-pr");
    expect(rows[1]).toHaveTextContent("Built-in");
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

    await screen.findByRole("table", { name: "Workflows" });
    expect(requests.some((r) => r.url.includes("project=agent-hub"))).toBe(true);
  });

  it("opens a workflow's detail when its row is chosen", async () => {
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

  it("has no serious a11y violations with a node open (a11y)", async () => {
    const { container } = renderDetail(aWorkflowDetail(), "?node=plan");

    await screen.findByRole("complementary", { name: "Node plan" });
    expect(await seriousViolations(container)).toEqual([]);
  });
});
