import { act, fireEvent, screen, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aBrainNote,
  aBrainTree,
  aBrainTreeOf,
  aKnowledgeResult,
  aKnowledgeSearch,
  aNoteBacklinks,
  aPage,
  aProblem,
  aProjectNow,
  aProjectSummary,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { SEARCH_DEBOUNCE_MS } from "../../lib/search";
import { BrainPickerScreen, BrainScreen, brainHome } from "./index";

const TREE = "/api/v1/projects/agent-hub/brain";
const NOTE = "/api/v1/projects/agent-hub/brain/note";
const SEARCH = "/api/v1/projects/agent-hub/knowledge/search";
const BACKLINKS = "/api/v1/projects/agent-hub/brain/backlinks";
const LEARNINGS = "/api/v1/learnings";
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
    routes: {
      [TREE]: aBrainTree(),
      [NOTE]: notes,
      [SEARCH]: aKnowledgeSearch(),
      [BACKLINKS]: aNoteBacklinks(),
      [LEARNINGS]: aPage([]),
      ...routes,
    },
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
const DEMO_BACKLINKS = "/api/v1/projects/demo/brain/backlinks";
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
      [DEMO_BACKLINKS]: aNoteBacklinks({ project: "demo" }),
      [LEARNINGS]: aPage([]),
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

/** The Brain's search field, once the tree has loaded. */
async function searchField(): Promise<HTMLElement> {
  const tree = screen.getByRole("navigation", { name: "Brain notes" });
  await within(tree).findByRole("link", { name: "Index" });
  return within(tree).getByRole("searchbox", { name: "Search brain notes and repo docs" });
}

function textSection(query: string, count: string): Promise<HTMLElement> {
  return screen.findByRole("region", { name: `Text matching “${query}” · ${count}` });
}

/** A layout below 900 px, where the note is stacked under the search (`(max-width: 899px)`). */
function stackedLayout() {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query === "(max-width: 899px)",
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
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
    expect(more).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(more);
    expect(within(paths).getAllByRole("link")).toHaveLength(10);
    expect(more).toHaveAccessibleName("Show the first 8");
    expect(more).toHaveAttribute("aria-expanded", "true");
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
    const field = await searchField();

    vi.useFakeTimers({ shouldAdvanceTime: false });
    try {
      fireEvent.change(field, { target: { value: "!!!" } });
      await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS + 50);
      expect(
        screen.getByText("Type a letter or a digit to search the text of notes."),
      ).toBeInTheDocument();
      expect(searchQueries(requests)).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("search: sends one request once typing pauses for the debounce", async () => {
    const { requests } = openDemo(aKnowledgeSearch({ results: worktreeResults() }));
    const field = await searchField();

    vi.useFakeTimers({ shouldAdvanceTime: false });
    try {
      for (const text of ["w", "work", "worktree", "worktrees"]) {
        fireEvent.change(field, { target: { value: text } });
        await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS - 20);
        expect(searchQueries(requests)).toEqual([]);
      }
      await vi.advanceTimersByTimeAsync(20);
      expect(searchQueries(requests)).toEqual(["worktrees"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("search: says a wordless query once, when typing pauses", async () => {
    openDemo(aKnowledgeSearch());
    const field = await searchField();
    const tree = screen.getByRole("navigation", { name: "Brain notes" });
    const said = () =>
      [...tree.querySelectorAll("[role='status']")].map((node) => node.textContent).join("");

    vi.useFakeTimers({ shouldAdvanceTime: false });
    try {
      fireEvent.change(field, { target: { value: "!" } });
      await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS - 20);
      expect(said()).toBe("");
      fireEvent.change(field, { target: { value: "!!" } });
      await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS - 20);
      expect(said()).toBe("");
      await vi.advanceTimersByTimeAsync(20);
      expect(said()).toBe("Nothing matches “!!”.");
    } finally {
      vi.useRealTimers();
    }
  });

  it("search: moves the focus to the note when a path match opens below 900 px", async () => {
    stackedLayout();
    try {
      openDemo(aKnowledgeSearch());
      await typeQuery("cleanup");
      const paths = await screen.findByRole("region", { name: "Paths matching “cleanup” · 1" });

      await userEvent.click(within(paths).getByRole("link"));

      await vi.waitFor(() => {
        expect(document.getElementById("brain-note-path")).toHaveFocus();
      });
    } finally {
      vi.unstubAllGlobals();
    }
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

  it("search: says to type a letter or a digit when the route refuses the query", async () => {
    openDemo(aProblem({ status: 400, title: "Invalid parameter", detail: "q: no words" }));

    await typeQuery("cleanup");

    const tree = screen.getByRole("navigation", { name: "Brain notes" });
    expect(
      await within(tree).findByText("Type a letter or a digit to search the text of notes."),
    ).toBeInTheDocument();
    expect(within(tree).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("search: moves the focus to the note when a result opens below 900 px", async () => {
    stackedLayout();
    try {
      openDemo(aKnowledgeSearch({ results: worktreeResults() }));
      await typeQuery("worktrees");
      const text = await textSection("worktrees", "3");

      await userEvent.click(within(text).getByRole("link", { name: "Cleanup after merge" }));

      await vi.waitFor(() => {
        expect(document.getElementById("brain-note-path")).toHaveFocus();
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("search: says an inbox result is unreviewed", async () => {
    openDemo(
      aKnowledgeSearch({
        results: [
          aKnowledgeResult({
            path: "brain/_inbox/web-gates.md",
            kind: "inbox",
            title: "Web gates",
            status: "proposed",
          }),
        ],
      }),
    );

    await typeQuery("gates");

    const text = await textSection("gates", "1");
    expect(within(text).getByText("inbox · unreviewed")).toBeInTheDocument();
  });

  it("search: says the server is not responding when the request gets no answer", async () => {
    openDemo(aKnowledgeSearch());
    vi.mocked(globalThis.fetch).mockRejectedValue(new TypeError("Failed to fetch"));

    await typeQuery("cleanup");

    const tree = screen.getByRole("navigation", { name: "Brain notes" });
    const problem = await within(tree).findByRole("alert");
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

/** A deep link to the middle note of `tree-3/`, one of the 600-note brain's folders of 100. */
const MIDDLE_NOTE = "/projects/agent-hub/brain/tree-3/note-050.md";
/** The last row of the 600-note brain once every folder is open. */
const LAST_NOTE = "/projects/agent-hub/brain/_inbox/proposal-3.md";

/** `note-001.md` to `note-<count>.md`: the notes `aBrainTreeOf` puts in each of its folders. */
function noteNames(count: number): string[] {
  return Array.from({ length: count }, (_, note) => `note-${String(note + 1).padStart(3, "0")}.md`);
}

/** The rows of the 600-note brain with `tree-3/` alone open, by accessible name, in tree order. */
const WITH_TREE_3_OPEN = [
  "Index",
  "Now",
  "tree-1, 100 notes",
  "tree-2, 100 notes",
  "tree-3, 100 notes",
  ...noteNames(100),
  "tree-4, 100 notes",
  "tree-5, 100 notes",
  "tree-6, 100 notes",
  "_inbox, 3 notes",
];

/** The tree box's height in jsdom: the virtualizer's fallback rect (1024 × 640), as DataTable's. */
const BOX = 640;
/** The height of what the box holds in jsdom: more than any tree here, so no scroll is capped. */
const CONTENT = 100_000;

/**
 * jsdom lays nothing out. Inside the tree's nav every element is BOX high and holds CONTENT, and
 * scrolling an element (`scrollTop`, `scrollTo`) moves its offset and fires `scroll` on the next
 * frame, as a browser does. `scrollIntoView` stays a no-op: jsdom has no box to bring into view.
 */
function layOutTree() {
  const offsets = new WeakMap<Element, number>();
  const inTree = (element: Element) => element.closest("nav[aria-label='Brain notes']") !== null;
  vi.spyOn(Element.prototype, "clientHeight", "get").mockImplementation(function (this: Element) {
    return inTree(this) ? BOX : 0;
  });
  vi.spyOn(Element.prototype, "scrollHeight", "get").mockImplementation(function (this: Element) {
    return inTree(this) ? CONTENT : 0;
  });
  vi.spyOn(Element.prototype, "scrollTop", "get").mockImplementation(function (this: Element) {
    return offsets.get(this) ?? 0;
  });
  vi.spyOn(Element.prototype, "scrollTop", "set").mockImplementation(function (
    this: Element,
    top: number,
  ) {
    offsets.set(this, Math.max(0, top));
    requestAnimationFrame(() => {
      this.dispatchEvent(new Event("scroll"));
    });
  });
  Object.defineProperty(Element.prototype, "scrollTo", {
    configurable: true,
    writable: true,
    value(this: Element, options?: ScrollToOptions | number, y?: number) {
      const top = typeof options === "number" ? y : options?.top;
      if (top !== undefined) this.scrollTop = top;
    },
  });
}

const brainNotes = () => screen.getByRole("navigation", { name: "Brain notes" });

/** Opens the Brain at `path` on `listing` (the 600-note brain by default), once its tree lists. */
async function openTree(path: string, listing = aBrainTreeOf(600)) {
  const shown = open(path, { [TREE]: listing });
  const nav = brainNotes();
  await within(nav).findByRole("region", { name: "Folders" }, { timeout: 5_000 });
  return { ...shown, nav };
}

/** The selected note's row, once the tree renders it. */
function selectedRow(nav: HTMLElement): Promise<HTMLElement> {
  return vi.waitFor(() => {
    const row = nav.querySelector<HTMLElement>("li a[aria-current='page']");
    if (row === null) throw new Error("the tree shows no selected note");
    return row;
  });
}

/** A folder row by its accessible name ("tree-3, 100 notes"); it must be rendered. */
const folderRow = (nav: HTMLElement, name: string) => within(nav).getByRole("button", { name });
/** A folder row by its accessible name, or null while the tree does not render it. */
const queryFolderRow = (nav: HTMLElement, name: string) =>
  within(nav).queryByRole("button", { name });
/** A note row by the note's name ("note-050.md"), or null while the tree does not render it. */
const queryNoteRow = (nav: HTMLElement, name: string) => within(nav).queryByRole("link", { name });
/** A note row by the note's path, or null while the tree does not render it. */
const noteLink = (nav: HTMLElement, path: string) =>
  nav.querySelector(`li a[href='/projects/agent-hub/brain/${path}']`);
const searchbox = (nav: HTMLElement) =>
  within(nav).getByRole("searchbox", { name: "Search brain notes and repo docs" });

/** Focus is on the tree's row named `name`: never on body, never outside the tree. */
function expectFocusOn(nav: HTMLElement, name: string) {
  expect(document.activeElement).toHaveAccessibleName(name);
  expect(nav.contains(document.activeElement)).toBe(true);
}

/** Opens the closed folder `name` with a click, which also gives its row focus. */
async function openByHand(user: UserEvent, nav: HTMLElement, name: string) {
  expect(folderRow(nav, name)).toHaveAttribute("aria-expanded", "false");
  await user.click(folderRow(nav, name));
  expect(folderRow(nav, name)).toHaveAttribute("aria-expanded", "true");
  expectFocusOn(nav, name);
}

/**
 * Scrolls the tree to `top`, as the wheel does. Which element of the nav scrolls is the tree's
 * own: every element between its groups and the nav moves.
 */
function scrollTreeTo(nav: HTMLElement, top: number) {
  const groups = within(nav).getByRole("region", { name: "Start here" });
  for (let box = groups.parentElement; box !== null && box !== nav; box = box.parentElement) {
    box.scrollTop = top;
    fireEvent.scroll(box);
  }
}

/** The rows the tree renders, in order: a note by its link, a folder by its text. */
function renderedRows(nav: HTMLElement): string[] {
  return [...nav.querySelectorAll("li")].map(
    (row) => row.querySelector("a")?.getAttribute("href") ?? row.textContent,
  );
}

/** Moves the fake clock by `ms`, then renders what its timers changed. */
function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

describe("BrainScreen tree", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
    layOutTree();
  });

  afterEach(() => {
    Reflect.deleteProperty(Element.prototype, "scrollTo");
    vi.useRealTimers();
  });

  it("renders fewer than 1,000 elements in the tree for a 600-note brain, and every note is reachable by scrolling", async () => {
    const listing = aBrainTreeOf(600);
    expect(listing.entries).toHaveLength(605);
    const user = userEvent.setup();
    const { nav } = await openTree(MIDDLE_NOTE, listing);
    expect(await selectedRow(nav)).toHaveAccessibleName("note-050.md");

    expect(nav.querySelectorAll("*").length).toBeLessThan(1000);

    // Every folder open, the lowest first, so the next one to click stays at the top.
    scrollTreeTo(nav, 0);
    expect(folderRow(nav, "tree-3, 100 notes")).toHaveAttribute("aria-expanded", "true");
    await user.click(folderRow(nav, "tree-3, 100 notes"));
    for (const folder of [
      "_inbox, 3 notes",
      "tree-6, 100 notes",
      "tree-5, 100 notes",
      "tree-4, 100 notes",
      "tree-3, 100 notes",
      "tree-2, 100 notes",
      "tree-1, 100 notes",
    ]) {
      await openByHand(user, nav, folder);
    }
    const reached = new Set<string>();
    let most = 0;
    for (let top = 0; top <= CONTENT && !reached.has(LAST_NOTE); top += BOX / 2) {
      scrollTreeTo(nav, top);
      most = Math.max(most, nav.querySelectorAll("*").length);
      for (const link of nav.querySelectorAll("li a")) reached.add(link.getAttribute("href") ?? "");
    }

    expect(most).toBeLessThan(1000);
    expect([...reached].sort()).toEqual(
      listing.entries.map((entry) => `/projects/agent-hub/brain/${entry.path}`).sort(),
    );
  }, 20_000);

  it("keeps the tree under 1,000 elements at the listing's 2,000-note cap", async () => {
    const listing = { ...aBrainTreeOf(1995), truncated: true };
    expect(listing.entries).toHaveLength(2000);
    expect(listing.entries.filter((entry) => entry.path.startsWith("tree-1/"))).toHaveLength(333);
    const { nav } = await openTree("/projects/agent-hub/brain/tree-1/note-200.md", listing);
    expect(await selectedRow(nav)).toHaveAccessibleName("note-200.md");

    expect(nav.querySelectorAll("*").length).toBeLessThan(1000);
  }, 20_000);

  it.each([
    { keys: "↓ and ↑", down: "{ArrowDown}", up: "{ArrowUp}" },
    { keys: "j and k", down: "j", up: "k" },
  ])(
    "moves focus row by row with ↓ and ↑, and with j and k, past the rendered rows and back, never to body ($keys)",
    async ({ down, up }) => {
      const user = userEvent.setup();
      const { nav } = await openTree("/projects/agent-hub/brain");
      await openByHand(user, nav, "tree-3, 100 notes");
      expect(queryNoteRow(nav, "note-100.md")).toBeNull();

      const from = WITH_TREE_3_OPEN.indexOf("tree-3, 100 notes");
      for (const name of WITH_TREE_3_OPEN.slice(from + 1)) {
        await user.keyboard(down);
        expectFocusOn(nav, name);
      }
      // The box followed focus to the last row: the rows before it show, the first ones do not.
      await vi.waitFor(() => {
        expect(queryFolderRow(nav, "tree-4, 100 notes")).not.toBeNull();
      });
      expect(queryFolderRow(nav, "tree-1, 100 notes")).toBeNull();

      for (const name of WITH_TREE_3_OPEN.slice(0, -1).reverse()) {
        await user.keyboard(up);
        expectFocusOn(nav, name);
      }
      await vi.waitFor(() => {
        expect(queryNoteRow(nav, "note-100.md")).toBeNull();
      });
      expect(queryFolderRow(nav, "tree-3, 100 notes")).not.toBeNull();
    },
    20_000,
  );

  it("goes to the first and the last row with Home and End", async () => {
    const user = userEvent.setup();
    const { nav } = await openTree("/projects/agent-hub/brain");
    await openByHand(user, nav, "tree-3, 100 notes");
    expect(queryFolderRow(nav, "_inbox, 3 notes")).toBeNull();

    await user.keyboard("{End}");
    expectFocusOn(nav, "_inbox, 3 notes");
    await vi.waitFor(() => {
      expect(queryFolderRow(nav, "tree-6, 100 notes")).not.toBeNull();
    });
    expect(queryFolderRow(nav, "tree-1, 100 notes")).toBeNull();

    await user.keyboard("{Home}");
    expectFocusOn(nav, "Index");
    await vi.waitFor(() => {
      expect(queryFolderRow(nav, "tree-1, 100 notes")).not.toBeNull();
    });
    expect(queryNoteRow(nav, "note-100.md")).toBeNull();
  });

  it.each([
    { keys: "→ and ←", opens: "{ArrowRight}", closes: "{ArrowLeft}" },
    { keys: "Enter", opens: "{Enter}", closes: "{Enter}" },
    { keys: "Space", opens: " ", closes: " " },
    { keys: "o", opens: "o", closes: "o" },
  ])(
    "opens and closes a folder with → and ←, Enter and Space, focus kept on its row ($keys)",
    async ({ opens, closes }) => {
      const user = userEvent.setup();
      const { nav } = await openTree("/projects/agent-hub/brain");
      await openByHand(user, nav, "tree-2, 100 notes");
      expect(noteLink(nav, "tree-2/note-001.md")).not.toBeNull();

      await user.keyboard(closes);
      expect(folderRow(nav, "tree-2, 100 notes")).toHaveAttribute("aria-expanded", "false");
      expectFocusOn(nav, "tree-2, 100 notes");
      expect(noteLink(nav, "tree-2/note-001.md")).toBeNull();

      await user.keyboard(opens);
      expect(folderRow(nav, "tree-2, 100 notes")).toHaveAttribute("aria-expanded", "true");
      expectFocusOn(nav, "tree-2, 100 notes");
      expect(noteLink(nav, "tree-2/note-001.md")).not.toBeNull();
    },
  );

  it.each([
    {
      from: "a note",
      path: MIDDLE_NOTE,
      listing: aBrainTreeOf(600),
      // A click on the open note keeps it open.
      pick: (nav: HTMLElement) => selectedRow(nav),
      row: "note-050.md",
      folder: "tree-3, 100 notes",
    },
    {
      from: "a closed folder",
      path: "/projects/agent-hub/brain/features/control-plane/plan.md",
      listing: aBrainTree(),
      // A click on the open folder closes it.
      pick: (nav: HTMLElement) => Promise.resolve(folderRow(nav, "control-plane, 1 note")),
      row: "control-plane, 1 note",
      folder: "features, 1 note",
    },
  ])(
    "moves from a row to its folder's row with ← ($from)",
    async ({ path, listing, pick, row, folder }) => {
      const user = userEvent.setup();
      const { nav } = await openTree(path, listing);
      await user.click(await pick(nav));
      expectFocusOn(nav, row);
      expect(document.activeElement?.getAttribute("aria-expanded") ?? "false").toBe("false");

      await user.keyboard("{ArrowLeft}");

      expectFocusOn(nav, folder);
      expect(folderRow(nav, folder)).toHaveAttribute("aria-expanded", "true");
    },
  );

  it("keeps a folder opened by hand open after it scrolls away and back", async () => {
    const user = userEvent.setup();
    const { nav } = await openTree("/projects/agent-hub/brain");
    await openByHand(user, nav, "tree-1, 100 notes");
    // Picking the open note takes focus, and the tree's current row, off the folder.
    await user.click(within(nav).getByRole("link", { name: "Index" }));
    expectFocusOn(nav, "Index");

    scrollTreeTo(nav, CONTENT);
    expect(queryFolderRow(nav, "tree-1, 100 notes")).toBeNull();
    scrollTreeTo(nav, 0);

    expect(folderRow(nav, "tree-1, 100 notes")).toHaveAttribute("aria-expanded", "true");
    expect(noteLink(nav, "tree-1/note-001.md")).not.toBeNull();
  });

  it("keeps a folder opened for an earlier note open when another note is picked", async () => {
    const user = userEvent.setup();
    const { nav, router } = await openTree(MIDDLE_NOTE);
    await selectedRow(nav);
    scrollTreeTo(nav, 0);
    expect(folderRow(nav, "tree-3, 100 notes")).toHaveAttribute("aria-expanded", "true");

    await user.click(within(nav).getByRole("link", { name: "Now" }));

    expect(router.state.location.pathname).toBe("/projects/agent-hub/brain/now.md");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Note now.md" }),
    ).toBeInTheDocument();
    expect(folderRow(nav, "tree-3, 100 notes")).toHaveAttribute("aria-expanded", "true");
    expect(noteLink(nav, "tree-3/note-001.md")).not.toBeNull();
  });

  it("keeps the tree one Tab stop, entering on the selected note", async () => {
    const user = userEvent.setup();
    const { nav } = await openTree(MIDDLE_NOTE);
    const selected = await selectedRow(nav);
    const rows = [...nav.querySelectorAll<HTMLElement>("li a, li button")];
    expect(rows.length).toBeGreaterThan(1);
    const stops = rows.filter((row) => row.tabIndex >= 0);
    expect(stops.length).toBe(1);
    expect(stops[0]).toBe(selected);

    await user.click(searchbox(nav));
    await user.tab();
    expect(selected).toHaveFocus();
    await user.tab();
    expect(within(nav).getByRole("link", { name: "Triage in Learnings" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(selected).toHaveFocus();
    await user.tab({ shift: true });
    expect(searchbox(nav)).toHaveFocus();
  });

  it("moves from an empty search field to the tree's current row with ↓", async () => {
    const user = userEvent.setup();
    const { nav } = await openTree(MIDDLE_NOTE);
    await selectedRow(nav);

    await user.keyboard("/");
    expect(searchbox(nav)).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expectFocusOn(nav, "note-050.md");

    // Once the user has used another row, that row is the current one.
    scrollTreeTo(nav, 0);
    await user.click(folderRow(nav, "tree-1, 100 notes"));
    await user.keyboard("/");
    expect(searchbox(nav)).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expectFocusOn(nav, "tree-1, 100 notes");
  });

  it("brings back the same open folders and scroll position when the search is cleared with Escape", async () => {
    const user = userEvent.setup();
    const { nav } = await openTree("/projects/agent-hub/brain");
    await openByHand(user, nav, "tree-2, 100 notes");
    scrollTreeTo(nav, 1_200);
    expect(queryFolderRow(nav, "tree-1, 100 notes")).toBeNull();
    const shown = renderedRows(nav);
    expect(
      shown.filter((row) => row.startsWith("/projects/agent-hub/brain/tree-2/")).length,
    ).toBeGreaterThan(10);

    await user.keyboard("/");
    await user.keyboard("note-0");
    expect(within(nav).queryByRole("region", { name: "Folders" })).toBeNull();
    await user.keyboard("{Escape}");

    expect(searchbox(nav)).toHaveValue("");
    await vi.waitFor(() => {
      expect(renderedRows(nav)).toEqual(shown);
    });
  });

  it("scrolls the selected row into view on a deep link without moving focus", async () => {
    const { nav } = await openTree(MIDDLE_NOTE);
    expect(await selectedRow(nav)).toHaveAccessibleName("note-050.md");

    await vi.waitFor(() => {
      expect(noteLink(nav, "tree-3/note-045.md")).not.toBeNull();
      expect(noteLink(nav, "tree-3/note-055.md")).not.toBeNull();
    });
    expect(queryNoteRow(nav, "Index")).toBeNull();
    expect(document.body).toHaveFocus();
  });

  it.each(["j", "k", "o"])(
    "leaves j, k and o to the search field while the user types in it (%s)",
    async (key) => {
      const user = userEvent.setup();
      const { nav, router } = await openTree(MIDDLE_NOTE);
      await user.click(await selectedRow(nav));
      await user.keyboard("{ArrowDown}");
      // The tree's current row is now a note other than the open one, which o would open.
      expectFocusOn(nav, "note-051.md");

      await user.keyboard("/");
      const field = searchbox(nav);
      expect(field).toHaveFocus();
      await user.keyboard(key);

      expect(field).toHaveValue(key);
      expect(field).toHaveFocus();
      expect(router.state.location.pathname).toBe("/projects/agent-hub/brain/tree-3/note-050.md");
    },
  );

  it("keeps Triage in Learnings at the end of the inbox group in a 600-note tree", async () => {
    const { nav } = await openTree(MIDDLE_NOTE);
    await selectedRow(nav);
    const inbox = within(nav).getByRole("region", { name: "Inbox · unreviewed" });

    scrollTreeTo(nav, 0);
    expect(queryNoteRow(nav, "Index")).not.toBeNull();
    expect(within(inbox).queryByText("_inbox/")).toBeNull();
    expect(within(inbox).getByRole("link", { name: "Triage in Learnings" })).toHaveAttribute(
      "href",
      "/knowledge/learnings?scope=agent-hub",
    );

    scrollTreeTo(nav, CONTENT);
    const order = [...inbox.querySelectorAll("*")];
    expect(
      order.indexOf(within(inbox).getByRole("link", { name: "Triage in Learnings" })),
    ).toBeGreaterThan(order.indexOf(within(inbox).getByText("_inbox/")));
  });

  it("shows the panel's skeleton after 300 ms while the listing loads (states)", () => {
    vi.useFakeTimers();
    open("/projects/agent-hub/brain", { [TREE]: "pending" });
    const nav = brainNotes();

    advance(299);
    expect(nav.querySelectorAll(".ah-skel")).toHaveLength(0);
    advance(1);
    // The field, a group heading and 10 rows, in the busy box.
    expect(nav.querySelectorAll(".ah-skel")).toHaveLength(12);
    expect(nav.querySelectorAll("[aria-busy='true'] .ah-skel")).toHaveLength(12);

    advance(699);
    expect(screen.queryByText("Loading brain notes")).toBeNull();
    advance(1);
    const said = screen.getByText("Loading brain notes");
    expect(said.closest(".ah-sr")).not.toBeNull();
    expect(said.closest("[role='status'], [aria-live='polite']")).not.toBeNull();
    // A screen reader may hold back what changes inside a busy element until it is no longer busy.
    expect(said.closest("[aria-busy='true']")).toBeNull();
  });

  it("has no serious a11y violations on a 600-note tree scrolled to the middle with a folder open (a11y)", async () => {
    const user = userEvent.setup();
    const { container, nav } = await openTree("/projects/agent-hub/brain");
    await openByHand(user, nav, "tree-3, 100 notes");
    scrollTreeTo(nav, 1_200);
    expect(queryFolderRow(nav, "tree-1, 100 notes")).toBeNull();
    expect(queryFolderRow(nav, "tree-6, 100 notes")).toBeNull();

    // The rows in view still say their level and their place among their siblings.
    const shownNotes = [...nav.querySelectorAll("li a[href^='/projects/agent-hub/brain/tree-3/']")];
    expect(shownNotes.length).toBeGreaterThan(10);
    for (const note of shownNotes) {
      const place = /note-(\d+)\.md$/.exec(note.getAttribute("href") ?? "")?.[1] ?? "";
      expect(note.closest("li")).toHaveAttribute("aria-level", "2");
      expect(note.closest("li")).toHaveAttribute("aria-setsize", "100");
      expect(note.closest("li")).toHaveAttribute("aria-posinset", String(Number(place)));
    }
    const folder = folderRow(nav, "tree-3, 100 notes").closest("li");
    expect(folder).toHaveAttribute("aria-level", "1");
    expect(folder).toHaveAttribute("aria-setsize", "6");
    expect(folder).toHaveAttribute("aria-posinset", "3");

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
