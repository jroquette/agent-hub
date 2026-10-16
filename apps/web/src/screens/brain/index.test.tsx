import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aBrainNote,
  aBrainTree,
  aPage,
  aProblem,
  aProjectNow,
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
    expect(await within(tree).findByRole("link", { name: "Index" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(tree).getByRole("link", { name: "index.md" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("caps the note's text at a readable line length (AC-270.7)", async () => {
    open();

    expect(await screen.findByRole("article")).toHaveClass("ah-brain-note");
  });

  it("leads back to the project through the breadcrumb", async () => {
    open();

    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "agent-hub" })).toHaveAttribute(
      "href",
      "/projects/agent-hub",
    );
    expect(within(crumbs).getByText("Brain")).toHaveAttribute("aria-current", "page");
    expect(await screen.findByText(/What agent-hub's agents know/)).toBeInTheDocument();
  });

  it("lists the notes in their folders and opens the selected note's folder", async () => {
    open("/projects/agent-hub/brain/features/control-plane/plan.md");

    const tree = screen.getByRole("navigation", { name: "Brain notes" });
    const plan = await within(tree).findByRole("link", { name: "plan.md" });
    expect(plan).toHaveAttribute("aria-current", "page");
    expect(plan.closest("details")).toHaveAttribute("open");
    expect(within(tree).getByText("decisions/").closest("details")).not.toHaveAttribute("open");
    expect(within(tree).getByRole("link", { name: "Now" })).toHaveAttribute(
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
    await userEvent.click(await within(tree).findByRole("link", { name: "Now" }));

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

    expect(await screen.findByText("No brain in this hub")).toBeInTheDocument();
    expect(screen.getByText(/Run .\/hub sync to create the skeleton/)).toBeInTheDocument();
  });

  it("groups the tree into start notes, folders with counts and the unreviewed inbox", async () => {
    open();

    const tree = screen.getByRole("navigation", { name: "Brain notes" });
    const start = await within(tree).findByRole("region", { name: "Start here" });
    expect(
      within(start)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Index", "Now"]);
    const folders = within(tree).getByRole("region", { name: "Folders" });
    expect(within(folders).getByText("features/").closest("summary")).toHaveAccessibleName(
      "features, 1 note",
    );
    expect(within(folders).queryByText("_inbox/")).not.toBeInTheDocument();
    const inbox = within(tree).getByRole("region", { name: "Inbox · unreviewed" });
    expect(within(inbox).getByText("_inbox/")).toBeInTheDocument();
    expect(within(inbox).getByRole("link", { name: "Triage in Learnings" })).toHaveAttribute(
      "href",
      "/knowledge/learnings?scope=agent-hub",
    );
  });

  it("filters the notes by path, focused with / and cleared with Escape", async () => {
    open();

    const tree = screen.getByRole("navigation", { name: "Brain notes" });
    await within(tree).findByRole("link", { name: "Index" });
    await userEvent.keyboard("/");
    const filter = within(tree).getByRole("searchbox", { name: "Filter brain notes" });
    expect(filter).toHaveFocus();

    await userEvent.type(filter, "plan");
    const matches = within(tree).getByRole("list", { name: "Matching notes" });
    expect(within(matches).getByRole("link")).toHaveAttribute(
      "href",
      "/projects/agent-hub/brain/features/control-plane/plan.md",
    );

    await userEvent.type(filter, "zzz");
    expect(within(tree).getByText(/No note matches/)).toBeInTheDocument();

    await userEvent.click(within(tree).getByRole("button", { name: "Clear filter" }));
    expect(filter).toHaveValue("");
    await userEvent.type(filter, "plan");

    await userEvent.keyboard("{Escape}");
    expect(filter).toHaveValue("");
    expect(within(tree).getByRole("region", { name: "Folders" })).toBeInTheDocument();
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

  it("counts each project's notes and shows its current focus", async () => {
    pick("/knowledge/brain", {
      [TREE]: aBrainTree(),
      "/api/v1/projects/agent-hub/now": aProjectNow(),
    });

    const row = (await screen.findByRole("link", { name: "agent-hub" })).closest("tr");
    if (row === null) throw new Error("no row");
    await within(row).findByText("Control plane MVP");
    await within(row).findByText("1 to triage");
    const cells = within(row)
      .getAllByRole("cell")
      .map((cell) => cell.textContent);
    expect(cells.slice(1)).toEqual(["Control plane MVP", "5", "1", "1", "0", "1 to triage"]);
    expect(within(row).getByRole("link", { name: "1 to triage" })).toHaveAttribute(
      "href",
      "/knowledge/learnings?scope=agent-hub",
    );
  });

  it("marks an incomplete count with + and a failed one with a dash (AC-270.4)", async () => {
    pick("/knowledge/brain", {
      "/api/v1/projects": aPage([
        aProjectSummary({ name: "agent-hub" }),
        aProjectSummary({ name: "broken" }),
      ]),
      [TREE]: aBrainTree({ truncated: true }),
      "/api/v1/projects/broken/brain": aProblem({ status: 500, title: "Boom" }),
    });

    const row = (await screen.findByRole("link", { name: "agent-hub" })).closest("tr");
    const broken = screen.getByRole("link", { name: "broken" }).closest("tr");
    if (row === null || broken === null) throw new Error("no row");
    expect(await within(row).findByText("5+")).toBeInTheDocument();
    expect((await within(broken).findAllByText("—")).length).toBeGreaterThan(0);
  });

  it("opens the project's brain when its row is clicked (AC-270.5)", async () => {
    const { router } = pick();

    const row = (await screen.findByRole("link", { name: "agent-hub" })).closest("tr");
    if (row === null) throw new Error("no row");
    await userEvent.click(within(row).getAllByRole("cell")[2] as HTMLElement);
    expect(router.state.location.pathname).toBe("/projects/agent-hub/brain");
  });

  it("says when a project records no current focus", async () => {
    pick("/knowledge/brain", {
      [TREE]: aBrainTree(),
      "/api/v1/projects/agent-hub/now": aProjectNow({ focus: [] }),
    });

    expect(await screen.findByText("No current focus recorded")).toBeInTheDocument();
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
