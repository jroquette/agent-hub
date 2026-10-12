import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aBrainNote,
  aBrainTree,
  aPage,
  aProblem,
  aProjectSummary,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { BrainPickerScreen, BrainScreen, brainHome } from "./index";

const TREE = "/api/v1/projects/agent-hub/brain";
const NOTE = "/api/v1/projects/agent-hub/brain/note";
const route = "projects/:project/brain/*";

/** Answers each note path with a note titled by its path. */
function notes(request: Request) {
  const path = new URL(request.url).searchParams.get("path") ?? "";
  return aBrainNote({
    path,
    markdown: `# Note ${path}\n\nSee [the decisions](decisions/index.md#d3).\n`,
  });
}

function open(path = "/projects/agent-hub/brain", routes: ApiRoutes = {}) {
  return renderWithApi(<BrainScreen />, {
    routes: { [TREE]: aBrainTree(), [NOTE]: notes, ...routes },
    path,
    route,
  });
}

function notePaths(requests: Request[]): (string | null)[] {
  return requests
    .filter((r) => new URL(r.url).pathname === NOTE)
    .map((r) => new URL(r.url).searchParams.get("path"));
}

describe("BrainScreen", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("opens index.md by default when the URL names no note", async () => {
    const { requests } = open();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Note index.md" }),
    ).toBeInTheDocument();
    expect(notePaths(requests)).toEqual(["index.md"]);
    const tree = screen.getByRole("navigation", { name: "Brain notes" });
    const links = await within(tree).findAllByRole("link", { name: "index.md" });
    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual(["page", null]);
  });

  it("lists the notes in their folders and opens the selected note's folder", async () => {
    open("/projects/agent-hub/brain/features/control-plane/plan.md");

    const tree = screen.getByRole("navigation", { name: "Brain notes" });
    const plan = await within(tree).findByRole("link", { name: "plan.md" });
    expect(plan).toHaveAttribute("aria-current", "page");
    expect(plan.closest("details")).toHaveAttribute("open");
    expect(within(tree).getByText("decisions/").closest("details")).not.toHaveAttribute("open");
    expect(within(tree).getByRole("link", { name: "now.md" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/brain/now.md",
    );
  });

  it("opens the note named by a deep link", async () => {
    const { requests } = open("/projects/agent-hub/brain/decisions/index.md");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Note decisions/index.md" }),
    ).toBeInTheDocument();
    expect(notePaths(requests)).toEqual(["decisions/index.md"]);
    expect(screen.getByText("brain/decisions/index.md")).toBeInTheDocument();
  });

  it("opens another note when it is picked in the tree", async () => {
    const { router } = open();

    const tree = screen.getByRole("navigation", { name: "Brain notes" });
    await userEvent.click(await within(tree).findByRole("link", { name: "now.md" }));

    expect(router.state.location.pathname).toBe("/projects/agent-hub/brain/now.md");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Note now.md" }),
    ).toBeInTheDocument();
  });

  it("follows a link between notes inside the app, anchor kept", async () => {
    const { router } = open();

    await userEvent.click(await screen.findByRole("link", { name: "the decisions" }));

    expect(router.state.location.pathname).toBe("/projects/agent-hub/brain/decisions/index.md");
    expect(router.state.location.hash).toBe("#d3");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Note decisions/index.md" }),
    ).toBeInTheDocument();
  });

  it("says the listing is incomplete when it was truncated or skipped entries", async () => {
    open("/projects/agent-hub/brain", { [TREE]: aBrainTree({ truncated: true, skipped: 3 }) });

    const tree = screen.getByRole("navigation", { name: "Brain notes" });
    const notice = await within(tree).findByRole("status");
    expect(notice).toHaveTextContent("The listing stopped at its limit");
    expect(notice).toHaveTextContent("3 entries were skipped");
  });

  it("says the brain is empty when it has no notes", async () => {
    open("/projects/agent-hub/brain", { [TREE]: aBrainTree({ entries: [] }) });

    expect(await screen.findByText("This brain has no notes yet.")).toBeInTheDocument();
  });

  it("still shows the note when the tree cannot be read", async () => {
    open("/projects/agent-hub/brain", {
      [TREE]: aProblem({ status: 503, title: "Hub not readable" }),
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Hub not readable");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Note index.md" }),
    ).toBeInTheDocument();
  });

  it("says a deep-linked note is missing when the API answers 404", async () => {
    open("/projects/agent-hub/brain/gone.md", {
      [NOTE]: aProblem({ status: 404, title: "Not found" }),
    });

    expect(await screen.findByText("No note gone.md in the agent-hub brain.")).toBeInTheDocument();
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = open("/projects/agent-hub/brain/features/control-plane/plan.md");
    await screen.findByRole("heading", { level: 1, name: "Note features/control-plane/plan.md" });
    await screen.findByRole("link", { name: "plan.md" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("BrainPickerScreen", () => {
  function pick(path = "/knowledge/brain", routes: ApiRoutes = {}) {
    return renderWithApi(<BrainPickerScreen />, {
      routes: {
        "/api/v1/projects": aPage([aProjectSummary({ name: "agent-hub" })]),
        ...routes,
      },
      path,
      route: "knowledge/brain",
    });
  }

  it("lists the projects to pick a brain when All projects is in scope", async () => {
    pick();

    expect(await screen.findByRole("link", { name: "agent-hub" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/brain",
    );
  });

  it("opens the scoped project's brain when a project is in scope", async () => {
    const { router } = renderWithApi(<BrainPickerScreen />, {
      path: "/knowledge/brain?scope=agent-hub",
      route: "*",
    });

    await vi.waitFor(() => {
      expect(router.state.location.pathname).toBe("/projects/agent-hub/brain");
    });
  });

  it("explains an empty project list", async () => {
    pick("/knowledge/brain", { "/api/v1/projects": aPage([]) });

    expect(await screen.findByText("No projects yet.")).toBeInTheDocument();
  });

  it("shows the problem when the projects cannot be read", async () => {
    pick("/knowledge/brain", { "/api/v1/projects": aProblem({ status: 500, title: "Boom" }) });

    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
  });

  it("encodes the project in the brain route", () => {
    expect(brainHome("a b")).toBe("/projects/a%20b/brain");
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = pick();
    await screen.findByRole("link", { name: "agent-hub" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
