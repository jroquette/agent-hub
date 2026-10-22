import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import {
  aKnowledgeResult,
  aKnowledgeSearch,
  aPage,
  aProblem,
  aSearchHit,
  renderWithApi,
  type ApiRoutes,
} from "../testing/builders";
import { CommandPalette } from "./CommandPalette";

const KNOWLEDGE = "/api/v1/projects/demo/knowledge/search";

/** The palette's search answers: a learning hit, and the demo brain's notes plus a repo doc. */
function brainRoutes(): ApiRoutes {
  return {
    "/api/v1/search": aPage([
      aSearchHit({
        kind: "learning",
        label: "Worktrees need a fresh fetch",
        href: "/knowledge/learnings/01923f1e",
        project: "demo",
      }),
    ]),
    [KNOWLEDGE]: aKnowledgeSearch({
      results: [
        aKnowledgeResult(),
        aKnowledgeResult({
          path: "demo-api/docs/guide.md",
          kind: "doc",
          title: "Repo guide",
          status: null,
        }),
        aKnowledgeResult({
          path: "brain/playbooks/cleanup.md",
          kind: "playbook",
          title: "Cleanup after merge",
          status: null,
        }),
      ],
    }),
  };
}

function groupNames(): (string | null)[] {
  return screen.getAllByRole("group").map((group) => group.getAttribute("aria-label"));
}

function knowledgeRequests(requests: Request[]): URL[] {
  return requests
    .map((request) => new URL(request.url))
    .filter((url) => url.pathname.endsWith("/knowledge/search"));
}

/** Holds every knowledge answer until `release` is called; the other routes answer at once. */
function holdKnowledge(): { release: () => void } {
  const answer = vi.mocked(globalThis.fetch).getMockImplementation();
  if (!answer) throw new Error("fetch is not stubbed");
  let release: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  vi.mocked(globalThis.fetch).mockImplementation(async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input));
    if (url.pathname.endsWith("/knowledge/search")) await gate;
    return answer(input, init);
  });
  return {
    release: () => {
      release?.();
    },
  };
}

describe("CommandPalette", () => {
  it("lists screens when the query is empty", () => {
    renderWithApi(<CommandPalette onClose={vi.fn()} />);

    expect(screen.getByRole("option", { name: /^Sessions/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Portfolio/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("one-tab: lists Sessions with g s and no Live sessions screen", () => {
    renderWithApi(<CommandPalette onClose={vi.fn()} />);

    const sessions = screen.getAllByRole("option").filter((o) => /sessions/i.test(o.textContent));
    expect(sessions).toHaveLength(1);
    expect(sessions[0]).toHaveTextContent(/^Sessions/);
    expect(sessions[0]).toHaveTextContent("g s");
  });

  it("groups search hits by kind when the query matches", async () => {
    renderWithApi(<CommandPalette onClose={vi.fn()} initialQuery="5091" />, {
      routes: {
        "/api/v1/search": aPage([
          aSearchHit(),
          aSearchHit({ kind: "run", label: "Run a1b2c3d4", href: "/runs/a1b2c3d4e5f6" }),
        ]),
      },
    });

    expect(await screen.findByText("Session 5091b986")).toBeInTheDocument();
    expect(screen.getByText("Sessions")).toHaveClass("ah-palette-group");
    expect(screen.getByText("Workflow runs")).toHaveClass("ah-palette-group");
  });

  it("opens the selected result with Enter after moving with the arrows", async () => {
    const onClose = vi.fn();
    const { router } = renderWithApi(<CommandPalette onClose={onClose} initialQuery="run" />, {
      routes: {
        "/api/v1/search": aPage([
          aSearchHit(),
          aSearchHit({ kind: "run", label: "Run a1b2c3d4", href: "/runs/a1b2c3d4e5f6" }),
        ]),
      },
    });
    await screen.findByText("Run a1b2c3d4");
    const input = screen.getByRole("combobox");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(router.state.location.pathname).toBe("/runs/a1b2c3d4e5f6");
    expect(onClose).toHaveBeenCalled();
  });

  it("drops a search hit whose href is not an in-app path", async () => {
    renderWithApi(<CommandPalette onClose={vi.fn()} initialQuery="run" />, {
      routes: {
        "/api/v1/search": aPage([
          aSearchHit({ kind: "run", label: "Run evil", href: "javascript:alert(1)" }),
          aSearchHit({ kind: "run", label: "Run outside", href: "//evil.example/x" }),
          aSearchHit({ kind: "run", label: "Run a1b2c3d4", href: "/runs/a1b2c3d4e5f6" }),
        ]),
      },
    });

    expect(await screen.findByText("Run a1b2c3d4")).toBeInTheDocument();
    expect(screen.queryByText("Run evil")).not.toBeInTheDocument();
    expect(screen.queryByText("Run outside")).not.toBeInTheDocument();
  });

  it("says what to try when nothing matches", async () => {
    renderWithApi(<CommandPalette onClose={vi.fn()} initialQuery="brain_memry" />, {
      routes: { "/api/v1/search": aPage([]) },
    });

    expect(
      await screen.findByText(/No match for "brain_memry". Try an issue key like AGH-48/),
    ).toBeInTheDocument();
  });

  it("debounces the search while typing", async () => {
    const { requests } = renderWithApi(<CommandPalette onClose={vi.fn()} />, {
      routes: { "/api/v1/search": aPage([]) },
    });
    const input = screen.getByRole("combobox");

    fireEvent.change(input, { target: { value: "ag" } });
    fireEvent.change(input, { target: { value: "agh" } });

    await waitFor(() => {
      expect(requests).toHaveLength(1);
    });
    expect(new URL(requests[0]?.url ?? "").searchParams.get("q")).toBe("agh");
  });

  it("closes on Escape and on a click outside", () => {
    const onClose = vi.fn();
    renderWithApi(<CommandPalette onClose={onClose} />);

    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    act(() => {
      fireEvent.click(screen.getByTestId("palette-scrim"));
    });

    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("brain notes: lists the scoped project's notes between the last group and Screens", async () => {
    const onClose = vi.fn();
    const { requests, router } = renderWithApi(
      <CommandPalette onClose={onClose} initialQuery="worktrees" project="demo" />,
      { routes: brainRoutes() },
    );

    const notes = await screen.findByRole("group", { name: "Brain notes" });
    expect(within(notes).getByText("Brain notes · demo")).toHaveAttribute("aria-hidden", "true");
    const rows = within(notes).getAllByRole("option");
    expect(rows.map((row) => row.getAttribute("aria-label"))).toEqual([
      "Worktrees from origin, brain/decisions/0001-worktrees.md",
      "Cleanup after merge, brain/playbooks/cleanup.md",
    ]);
    expect(screen.queryByText("Repo guide")).not.toBeInTheDocument();
    expect(groupNames()).toEqual(["Learnings", "Brain notes"]);
    const [asked] = knowledgeRequests(requests);
    expect(asked?.searchParams.get("q")).toBe("worktrees");
    expect(asked?.searchParams.get("limit")).toBe("8");
    expect(screen.getByRole("combobox")).toHaveAttribute(
      "placeholder",
      "Search sessions, runs, issues, files, agents, notes, screens…",
    );

    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(rows[0]).toHaveAttribute("aria-selected", "true");
    expect(input).toHaveAttribute("aria-activedescendant", rows[0]?.id);
    fireEvent.keyDown(input, { key: "Enter" });

    expect(router.state.location.pathname).toBe("/projects/demo/brain/decisions/0001-worktrees.md");
    expect(onClose).toHaveBeenCalled();
  });

  it("brain notes: sends no request with All projects in scope", async () => {
    const { requests } = renderWithApi(
      <CommandPalette onClose={vi.fn()} initialQuery="worktrees" project={null} />,
      { routes: brainRoutes() },
    );

    expect(await screen.findByText("Worktrees need a fresh fetch")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Brain notes" })).not.toBeInTheDocument();
    expect(knowledgeRequests(requests)).toEqual([]);
    expect(
      screen.getByText("Brain notes are searched when a project is in scope."),
    ).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveAttribute(
      "placeholder",
      "Search sessions, runs, issues, files, agents, screens…",
    );
  });

  it("brain notes: searches the route's project on a project route", async () => {
    const { requests } = renderWithApi(
      <CommandPalette onClose={vi.fn()} initialQuery="worktrees" project={null} />,
      { routes: brainRoutes(), path: "/projects/demo/config" },
    );

    expect(await screen.findByRole("group", { name: "Brain notes" })).toBeInTheDocument();
    expect(knowledgeRequests(requests).map((url) => url.pathname)).toEqual([KNOWLEDGE]);
    expect(
      screen.queryByText("Brain notes are searched when a project is in scope."),
    ).not.toBeInTheDocument();
  });

  it("brain notes: sends no request when the query has no letter or digit", async () => {
    const { requests } = renderWithApi(
      <CommandPalette onClose={vi.fn()} initialQuery="!!!" project="demo" />,
      { routes: { ...brainRoutes(), "/api/v1/search": aPage([]) } },
    );

    expect(await screen.findByText(/No match for "!!!"/)).toBeInTheDocument();
    expect(knowledgeRequests(requests)).toEqual([]);
  });

  it("brain notes: hides the group and says so in the foot when the request fails", async () => {
    renderWithApi(<CommandPalette onClose={vi.fn()} initialQuery="worktrees" project="demo" />, {
      routes: {
        ...brainRoutes(),
        [KNOWLEDGE]: aProblem({
          status: 502,
          title: "Could not read the hub's files",
          detail: "brain: git exited with 128: fatal: not a git repository",
        }),
      },
    });

    expect(
      await screen.findByText("Brain notes not searched: Could not read the hub's files."),
    ).toHaveAttribute("role", "status");
    expect(screen.queryByRole("group", { name: "Brain notes" })).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Learnings" })).toBeInTheDocument();
    expect(screen.queryByText(/No match for/)).not.toBeInTheDocument();
  });

  it("brain notes: keeps the highlighted row when the group arrives late", async () => {
    const onClose = vi.fn();
    const { router } = renderWithApi(<CommandPalette onClose={onClose} project="demo" />, {
      routes: {
        ...brainRoutes(),
        "/api/v1/search": aPage([aSearchHit({ label: "Session brain01" })]),
      },
    });
    const late = holdKnowledge();
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "brain" } });
    await screen.findByText("Session brain01");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    const brainScreen = screen.getByRole("option", { name: /^Brain/ });
    expect(brainScreen).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText(/No match for/)).not.toBeInTheDocument();
    const notes = await screen.findByRole("group", { name: "Brain notes" }, { timeout: 2000 });
    expect(within(notes).queryAllByRole("option")).toEqual([]);

    act(() => {
      late.release();
    });

    await screen.findByRole("option", { name: /Worktrees from origin/ });
    expect(groupNames()).toEqual(["Sessions", "Brain notes", "Screens"]);
    const arrived = screen.getByRole("group", { name: "Brain notes" });
    expect(within(arrived).getAllByRole("option")).toHaveLength(2);
    expect(screen.getByRole("option", { name: /^Brain/ })).toHaveAttribute("aria-selected", "true");
    expect(input).toHaveAttribute(
      "aria-activedescendant",
      screen.getByRole("option", { name: /^Brain/ }).id,
    );
    fireEvent.keyDown(input, { key: "Enter" });
    expect(router.state.location.pathname).toBe("/knowledge/brain");
  });

  it("brain notes group has no serious a11y violations (a11y)", async () => {
    const shown = renderWithApi(
      <CommandPalette onClose={vi.fn()} initialQuery="worktrees" project="demo" />,
      { routes: brainRoutes() },
    );
    await screen.findByRole("group", { name: "Brain notes" });
    expect(await seriousViolations(shown.container)).toEqual([]);
    shown.unmount();

    const failed = renderWithApi(
      <CommandPalette onClose={vi.fn()} initialQuery="worktrees" project="demo" />,
      { routes: { ...brainRoutes(), [KNOWLEDGE]: aProblem({ status: 502, title: "Boom" }) } },
    );
    await screen.findByText("Brain notes not searched: Boom.");
    expect(await seriousViolations(failed.container)).toEqual([]);
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = renderWithApi(<CommandPalette onClose={vi.fn()} />);

    expect(await seriousViolations(container)).toEqual([]);
  });
});
