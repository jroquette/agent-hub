import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aBrainNote,
  aBrainTree,
  aKnowledgeResult,
  aKnowledgeSearch,
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
const SEARCH = "/api/v1/projects/agent-hub/knowledge/search";
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
    routes: { [TREE]: aBrainTree(), [NOTE]: notes, [SEARCH]: aKnowledgeSearch(), ...routes },
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
    const filter = within(tree).getByRole("searchbox", {
      name: "Search brain notes and repo docs",
    });
    expect(filter).toHaveFocus();

    await userEvent.type(filter, "plan");
    const matches = within(tree).getByRole("list", { name: "Matching notes" });
    expect(within(matches).getByRole("link")).toHaveAttribute(
      "href",
      "/projects/agent-hub/brain/features/control-plane/plan.md?q=plan",
    );

    await userEvent.type(filter, "zzz");
    expect(await within(tree).findByText(/Nothing matches/, { selector: "p" })).toBeInTheDocument();

    await userEvent.click(within(tree).getByRole("button", { name: "Clear search" }));
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

const DEMO_TREE = "/api/v1/projects/demo/brain";
const DEMO_NOTE = "/api/v1/projects/demo/brain/note";
const DEMO_SEARCH = "/api/v1/projects/demo/knowledge/search";
const NO_REPO_DOC = "Repo docs are not opened in the app";

/** AC-393.3's answer: the decision, a playbook and a repo doc, best first. */
function worktreeResults() {
  return [
    aKnowledgeResult(),
    aKnowledgeResult({
      path: "brain/playbooks/cleanup.md",
      kind: "playbook",
      title: "Cleanup after merge",
      status: null,
      snippet: "remove the worktrees once the branch is merged",
    }),
    aKnowledgeResult({
      path: "demo-api/docs/guide.md",
      kind: "doc",
      title: "Repo guide",
      status: null,
      snippet: "create worktrees with make worktree",
    }),
  ];
}

/** Project demo's Brain: a small tree, every note served, and the search answered by `search`. */
function openDemo(
  search: ApiRoutes[string],
  path = "/projects/demo/brain",
  routes: ApiRoutes = {},
) {
  return renderWithApi(<BrainScreen />, {
    routes: {
      [DEMO_TREE]: aBrainTree({
        project: "demo",
        entries: [
          { path: "decisions/0001-worktrees.md", size: 120 },
          { path: "index.md", size: 80 },
          { path: "playbooks/cleanup.md", size: 90 },
        ],
      }),
      [DEMO_NOTE]: notes,
      [DEMO_SEARCH]: search,
      ...routes,
    },
    path,
    route,
  });
}

function searchQueries(requests: Request[]): (string | null)[] {
  return requests
    .map((request) => new URL(request.url))
    .filter((url) => url.pathname === DEMO_SEARCH)
    .map((url) => url.searchParams.get("q"));
}

async function typeQuery(text: string): Promise<HTMLElement> {
  const tree = screen.getByRole("navigation", { name: "Brain notes" });
  await within(tree).findByRole("link", { name: "Index" });
  await userEvent.keyboard("/");
  const field = within(tree).getByRole("searchbox", { name: "Search brain notes and repo docs" });
  expect(field).toHaveFocus();
  await userEvent.type(field, text);
  return field;
}

function textSection(query: string, count: string): Promise<HTMLElement> {
  return screen.findByRole("region", { name: `Text matching “${query}” · ${count}` });
}

describe("BrainScreen search", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("search: shows path and text matches after the debounce", async () => {
    const { requests, router } = openDemo(aKnowledgeSearch({ results: worktreeResults() }));

    const field = await typeQuery("worktrees");

    expect(field).toHaveAttribute("placeholder", "Search notes and repo docs");
    expect(field).toHaveAttribute("maxlength", "500");
    expect(router.state.location.search).toBe("?q=worktrees");
    const paths = screen.getByRole("region", { name: "Paths matching “worktrees” · 1" });
    expect(within(paths).getByRole("link", { name: /0001-worktrees\.md/ })).toHaveAttribute(
      "href",
      "/projects/demo/brain/decisions/0001-worktrees.md?q=worktrees",
    );
    const text = await textSection("worktrees", "3");
    expect(searchQueries(requests)).toEqual(["worktrees"]);
    expect(
      new URL(requests.find((r) => r.url.includes("knowledge"))?.url ?? "").searchParams.has(
        "limit",
      ),
    ).toBe(false);
    const decision = within(text).getByRole("link", { name: "Worktrees from origin" });
    expect(decision).toHaveAccessibleDescription(
      /brain\/decisions\/0001-worktrees\.md.*decision · accepted.*every task runs in its own worktrees/,
    );
    expect(
      within(text).getByRole("link", { name: "Cleanup after merge" }),
    ).toHaveAccessibleDescription(/playbook/);
    expect(within(text).queryByRole("link", { name: /Repo guide/ })).not.toBeInTheDocument();
    const guide = within(text).getByText("Repo guide").closest("li");
    expect(guide).toHaveTextContent("demo-api/docs/guide.md");
    expect(guide).toHaveTextContent("doc · repo doc, not opened here");
    expect(guide).toHaveTextContent("create worktrees with make worktree");
    expect(within(guide as HTMLElement).getByRole("tooltip", { hidden: true })).toHaveTextContent(
      NO_REPO_DOC,
    );
    expect(await screen.findByText("1 path and 3 text matches for “worktrees”.")).toHaveClass(
      "ah-sr",
    );

    await userEvent.click(decision);

    expect(router.state.location.pathname).toBe("/projects/demo/brain/decisions/0001-worktrees.md");
    expect(router.state.location.search).toBe("?q=worktrees");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Note decisions/0001-worktrees.md" }),
    ).toBeInTheDocument();
    expect(decision).toHaveAttribute("aria-current", "page");
    expect(decision).toHaveFocus();
    expect(field).toHaveValue("worktrees");
  });

  it("search: keeps the query when a link inside the note is followed", async () => {
    const { router } = openDemo(aKnowledgeSearch(), "/projects/demo/brain/index.md?q=worktrees");

    expect(
      await screen.findByRole("searchbox", { name: "Search brain notes and repo docs" }),
    ).toHaveValue("worktrees");
    await userEvent.click(await screen.findByRole("link", { name: "the decisions" }));

    expect(router.state.location.pathname).toBe("/projects/demo/brain/decisions/index.md");
    expect(router.state.location.search).toBe("?q=worktrees");
    expect(router.state.location.hash).toBe("#d3");
  });

  it("search: shows the first 8 path matches, then Show all", async () => {
    const entries = Array.from({ length: 10 }, (_, i) => ({
      path: `guides/topic-${String(i).padStart(2, "0")}.md`,
      size: 10,
    }));
    openDemo(aKnowledgeSearch(), "/projects/demo/brain", {
      [DEMO_TREE]: aBrainTree({
        project: "demo",
        entries: [{ path: "index.md", size: 1 }, ...entries],
      }),
    });

    await typeQuery("topic");

    const paths = screen.getByRole("region", { name: "Paths matching “topic” · 10" });
    expect(within(paths).getAllByRole("link")).toHaveLength(8);
    const more = within(paths).getByRole("button", { name: "Show all 10 path matches" });
    await userEvent.click(more);
    expect(within(paths).getAllByRole("link")).toHaveLength(10);
    expect(more).toHaveAccessibleName("Show the first 8");
    expect(more).toHaveFocus();
  });

  it("search: keeps the path filter narrowing the tree", async () => {
    openDemo(aKnowledgeSearch({ query: "cleanup", results: [] }));

    await typeQuery("cleanup");

    const tree = screen.getByRole("navigation", { name: "Brain notes" });
    expect(within(tree).queryByRole("region", { name: "Folders" })).not.toBeInTheDocument();
    const matches = within(tree).getByRole("list", { name: "Matching notes" });
    expect(
      within(matches)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["cleanup.mdplaybooks/"]);
    await vi.waitFor(() => {
      expect(screen.getByText("1 path and 0 text matches for “cleanup”.")).toBeInTheDocument();
    });
    expect(screen.queryByRole("region", { name: /Text matching/ })).not.toBeInTheDocument();
  });

  it("search: says nothing matches, with a hint for several words", async () => {
    openDemo(aKnowledgeSearch({ results: [] }));

    const field = await typeQuery("zebra crossing");

    const tree = screen.getByRole("navigation", { name: "Brain notes" });
    expect(
      await within(tree).findByText("Nothing matches “zebra crossing”.", { selector: "p" }),
    ).toBeInTheDocument();
    expect(within(tree).getByText("Every word must appear: try fewer words.")).toBeInTheDocument();
    await userEvent.clear(field);
    await userEvent.type(field, "zebra");
    expect(await within(tree).findByText("No note path or text contains it.")).toBeInTheDocument();
  });

  it("search: says the query has no word", async () => {
    const { requests } = openDemo(aKnowledgeSearch());

    await typeQuery("!!!");

    expect(
      await screen.findByText("Type a letter or a digit to search the text of notes."),
    ).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(searchQueries(requests)).toEqual([]);
  });

  it("search: shows the problem with Try again when the search fails", async () => {
    let calls = 0;
    openDemo(() => {
      calls += 1;
      return calls === 1
        ? aProblem({
            status: 502,
            title: "Could not read the hub's files",
            detail: "brain: git exited with 128: fatal: not a git repository",
          })
        : aKnowledgeSearch({ query: "cleanup", results: worktreeResults().slice(1, 2) });
    });

    await typeQuery("cleanup");

    const tree = screen.getByRole("navigation", { name: "Brain notes" });
    const problem = await within(tree).findByRole("alert");
    expect(problem).toHaveTextContent("Could not read the hub's files");
    expect(problem).toHaveTextContent("brain: git exited with 128: fatal: not a git repository");
    expect(within(tree).getByRole("list", { name: "Matching notes" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Note index.md" })).toBeInTheDocument();

    await userEvent.click(within(problem).getByRole("button", { name: "Try again" }));

    const text = await textSection("cleanup", "1");
    expect(within(text).getByRole("link", { name: "Cleanup after merge" })).toBeInTheDocument();
  });

  it("search: says the server is not responding when the request gets no answer", async () => {
    openDemo(aKnowledgeSearch());
    vi.mocked(globalThis.fetch).mockRejectedValue(new TypeError("Failed to fetch"));

    await typeQuery("cleanup");

    const problem = await screen.findByRole("alert");
    expect(problem).toHaveTextContent("The app's server is not responding");
    expect(problem).toHaveTextContent("Check that hub web is still running, then try again.");
  });

  it("search: shows each warning and the skipped files", async () => {
    openDemo(
      aKnowledgeSearch({
        results: [aKnowledgeResult({ provenance: "agent-from-external" })],
        warnings: ["demo-web: not checked out; its docs are not searched"],
        skipped: [
          { path: "brain/_inbox/leak.md", reason: "secret" },
          { path: "brain/big.md", reason: "too large" },
        ],
      }),
    );

    await typeQuery("worktrees");

    const text = await textSection("worktrees", "1");
    const warning = within(text).getByText("demo-web: not checked out; its docs are not searched");
    expect(warning.closest(".ah-banner")).not.toHaveAttribute("role");
    expect(within(text).getByText("External content · not verified")).toBeInTheDocument();
    expect(
      within(text).getByText(
        "2 files were not searched (a secret rule matched, too large, or unreadable).",
      ),
    ).toBeInTheDocument();
    const which = within(text).getByRole("button", { name: "Show which" });
    expect(which).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(which);
    expect(which).toHaveAttribute("aria-expanded", "true");
    expect(within(text).getByText("brain/_inbox/leak.md · secret")).toBeInTheDocument();
    expect(within(text).getByText("brain/big.md · too large")).toBeInTheDocument();
  });

  it("search: says the 50 best are shown", async () => {
    const results = Array.from({ length: 50 }, (_, i) =>
      aKnowledgeResult({ path: `brain/notes/n${String(i)}.md`, title: `Note ${String(i)}` }),
    );
    openDemo(aKnowledgeSearch({ results }));

    await typeQuery("worktrees");

    const text = await textSection("worktrees", "50 best");
    expect(
      within(text).getByText("Showing the 50 best matches. Add a word to narrow the search."),
    ).toBeInTheDocument();
  });

  it("search: shows a skeleton, then says a first search can take a few seconds", async () => {
    openDemo("pending");

    await typeQuery("worktrees");

    const tree = screen.getByRole("navigation", { name: "Brain notes" });
    await vi.waitFor(() => {
      expect(tree.querySelector("[aria-busy='true'] .ah-skel")).not.toBeNull();
    });
    expect(
      await within(tree).findByText(
        "Reading the hub's notes for this search. A first search after an update can take a few seconds.",
        {},
        { timeout: 3000 },
      ),
    ).toBeInTheDocument();
    expect(within(tree).getByText("Searching notes")).toHaveClass("ah-sr");
  });

  it("search: moves between results with the arrow keys and j k", async () => {
    const { router } = openDemo(aKnowledgeSearch({ results: worktreeResults() }));

    const field = await typeQuery("worktrees");
    const text = await textSection("worktrees", "3");
    const paths = screen.getByRole("region", { name: "Paths matching “worktrees” · 1" });
    const pathRow = within(paths).getByRole("link");
    const decision = within(text).getByRole("link", { name: "Worktrees from origin" });
    const cleanup = within(text).getByRole("link", { name: "Cleanup after merge" });
    const guide = within(text).getByText("Repo guide").closest("li");

    await userEvent.keyboard("{ArrowDown}");
    expect(pathRow).toHaveFocus();
    await userEvent.keyboard("j");
    expect(decision).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(cleanup).toHaveFocus();
    await userEvent.keyboard("j");
    expect(guide).toHaveFocus();
    await userEvent.keyboard("k");
    expect(cleanup).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    expect(decision).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(field).toHaveFocus();
    expect(field).toHaveValue("worktrees");
    await userEvent.keyboard("{ArrowDown}");
    await userEvent.keyboard("{ArrowUp}");
    expect(field).toHaveFocus();

    await userEvent.keyboard("{ArrowDown}");
    await userEvent.keyboard("j");
    await userEvent.keyboard("{Enter}");
    expect(router.state.location.pathname).toBe("/projects/demo/brain/decisions/0001-worktrees.md");
  });

  it("search: sends the search at once when Enter is pressed in the field", async () => {
    const { requests } = openDemo(aKnowledgeSearch({ results: worktreeResults() }));
    const tree = screen.getByRole("navigation", { name: "Brain notes" });
    await within(tree).findByRole("link", { name: "Index" });
    const field = within(tree).getByRole("searchbox", { name: "Search brain notes and repo docs" });

    vi.useFakeTimers({ shouldAdvanceTime: false });
    try {
      fireEvent.change(field, { target: { value: "worktrees" } });
      fireEvent.keyDown(field, { key: "Enter" });
      await vi.advanceTimersByTimeAsync(10);
      expect(searchQueries(requests)).toEqual(["worktrees"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("search panel has no serious a11y violations (a11y)", async () => {
    const results = openDemo(
      aKnowledgeSearch({
        results: worktreeResults(),
        warnings: ["demo-web: not checked out; its docs are not searched"],
        skipped: [{ path: "brain/big.md", reason: "too large" }],
      }),
    );
    await typeQuery("worktrees");
    await textSection("worktrees", "3");
    expect(await seriousViolations(results.container)).toEqual([]);
    results.unmount();

    const none = openDemo(aKnowledgeSearch());
    await typeQuery("zebra");
    await screen.findByText("Nothing matches “zebra”.", { selector: "p" });
    expect(await seriousViolations(none.container)).toEqual([]);
    none.unmount();

    const failed = openDemo(aProblem({ status: 502, title: "Could not read the hub's files" }));
    await typeQuery("cleanup");
    await screen.findByRole("alert");
    expect(await seriousViolations(failed.container)).toEqual([]);
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

  it("counts each project's notes and shows its current focus (AC-270.1, AC-270.2)", async () => {
    pick("/knowledge/brain", {
      [TREE]: aBrainTree(),
      "/api/v1/projects/agent-hub/now": aProjectNow(),
    });

    const card = await screen.findByRole("article", { name: "agent-hub" });
    await within(card).findByText("Current focus: Control plane MVP");
    await within(card).findByText("1 to triage in Learnings");
    const values = [...card.querySelectorAll(".ah-pcard-stat")].map((stat) => [
      stat.querySelector(".ah-pcard-k")?.textContent,
      stat.querySelector(".ah-pcard-v")?.textContent,
    ]);
    expect(values).toEqual([
      ["Notes", "5"],
      ["Features", "1"],
      ["Decisions", "1"],
      ["Learnings", "0"],
    ]);
    expect(
      within(card).getByRole("link", { name: "1 to triage in Learnings for agent-hub" }),
    ).toHaveAttribute("href", "/knowledge/learnings?scope=agent-hub");
  });

  it("says the inbox is empty when nothing waits for triage (AC-270.2)", async () => {
    pick("/knowledge/brain", {
      [TREE]: aBrainTree({ entries: [] }),
      "/api/v1/projects/agent-hub/now": aProjectNow(),
    });

    const card = await screen.findByRole("article", { name: "agent-hub" });
    expect(await within(card).findByText("Inbox empty")).toBeInTheDocument();
  });

  it("marks an incomplete count with + and a failed one with a dash and a Retry (AC-270.4, AC-427.13)", async () => {
    pick("/knowledge/brain", {
      "/api/v1/projects": aPage([
        aProjectSummary({ name: "agent-hub" }),
        aProjectSummary({ name: "broken" }),
      ]),
      [TREE]: aBrainTree({ truncated: true }),
      "/api/v1/projects/broken/brain": aProblem({ status: 500, title: "Boom" }),
    });

    const card = await screen.findByRole("article", { name: "agent-hub" });
    const broken = screen.getByRole("article", { name: "broken" });
    expect(await within(card).findByText("5+")).toBeInTheDocument();
    expect((await within(broken).findAllByText("—")).length).toBeGreaterThan(0);
    expect(within(broken).getByText("Could not read this brain: Boom.")).toBeInTheDocument();
    expect(within(broken).getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("opens the project's brain when its card is clicked (AC-270.5)", async () => {
    const { router } = pick();

    const card = await screen.findByRole("article", { name: "agent-hub" });
    await userEvent.click(card);
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
