import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aBrainNote,
  aBrainTree,
  aLearning,
  aNoteBacklinks,
  aPage,
  aProblem,
  at,
  renderWithApi,
  type ApiRoutes,
  type BrainNote,
  type Learning,
} from "../../testing/builders";
import { BrainScreen } from "./index";

const TREE = "/api/v1/projects/agent-hub/brain";
const NOTE = "/api/v1/projects/agent-hub/brain/note";
const BACKLINKS = "/api/v1/projects/agent-hub/brain/backlinks";
const LEARNINGS = "/api/v1/learnings";
const route = "projects/:project/brain/*";
const ORIGIN = "Where this note came from";
const NOTHING = "No provenance recorded for this note.";

/** `index.md` of project agent-hub on the Brain screen, with `frontmatter` and `learnings`. */
function open(
  frontmatter: BrainNote["frontmatter"],
  learnings: ApiRoutes[string] = aPage([]),
  routes: ApiRoutes = {},
) {
  return renderWithApi(<BrainScreen />, {
    routes: {
      [TREE]: aBrainTree(),
      [NOTE]: aBrainNote({ frontmatter }),
      [BACKLINKS]: aNoteBacklinks(),
      [LEARNINGS]: learnings,
      ...routes,
    },
    path: "/projects/agent-hub/brain",
    route,
  });
}

function accepted(overrides: Partial<Learning> = {}): Learning {
  return aLearning({
    id: "l-1",
    text: "Proposal: Run the screen a11y tests before the PR",
    status: "accepted",
    state: "in_brain",
    brain_path: "brain/index.md",
    decided_at: at(900),
    decided_by: "José Henrique Roquette",
    source_session_id: "s1",
    ...overrides,
  });
}

function origin(): Promise<HTMLElement> {
  return screen.findByRole("region", { name: ORIGIN });
}

describe("BrainScreen Where this note came from", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("came from: shows provenance, sources, the learning and its session (AC-393.16)", async () => {
    const { requests } = open(
      { type: "learning", provenance: "agent", sources: ["a", "b"] },
      aPage([accepted()]),
    );

    const section = await origin();
    const learning = await within(section).findByRole("link", {
      name: "Run the screen a11y tests before the PR",
    });
    expect(learning).toHaveAttribute("href", "/knowledge/learnings/l-1");
    expect(within(section).getByText("In brain")).toBeInTheDocument();
    const session = within(section).getByRole("link", { name: "Session s1" });
    expect(session).toHaveAttribute("href", "/sessions/s1");
    expect(session).toHaveTextContent("session s1");
    expect(within(section).getByText("agent")).toBeInTheDocument();
    for (const source of ["a", "b"]) {
      const item = within(section).getByText(source);
      expect(item.closest("a")).toBeNull();
    }
    expect(within(section).getByText(/^Accepted/)).toHaveTextContent(
      "Accepted 11 Oct 2026 by José Henrique Roquette",
    );
    const chips = screen.getByRole("list", { name: "Frontmatter" });
    expect(chips).toHaveTextContent("type: learning");
    expect(chips).not.toHaveTextContent("provenance");
    expect(chips).not.toHaveTextContent("sources");
    const asked = new URL(requests.find((r) => r.url.includes(LEARNINGS))?.url ?? "");
    expect(Object.fromEntries(asked.searchParams)).toEqual({
      project: "agent-hub",
      brain_path: "index.md",
      status: "accepted",
      limit: "10",
    });
  });

  it("came from: links the frontmatter session when no learning names one", async () => {
    open({ type: "learning", session: "s-123" });

    const section = await origin();
    const session = await within(section).findByRole("link", { name: "Session s-123" });
    expect(session).toHaveAttribute("href", "/sessions/s-123");
    expect(within(section).getByText("From the note's frontmatter.")).toBeInTheDocument();
    expect(within(section).getByRole("tooltip")).toHaveTextContent(
      "Opens the session if this app collected it.",
    );
    expect(screen.getByRole("list", { name: "Frontmatter" })).not.toHaveTextContent("session");
  });

  it("came from: keeps the session chip when a learning names the session", async () => {
    open({ type: "learning", session: "s-123" }, aPage([accepted()]));

    const section = await origin();
    await within(section).findByRole("link", { name: "Session s1" });
    expect(screen.getByRole("list", { name: "Frontmatter" })).toHaveTextContent("session: s-123");
  });

  it("came from: links only the learning's session when the frontmatter names another", async () => {
    open({ session: "s-123" }, aPage([accepted()]));

    const section = await origin();
    await within(section).findByRole("link", { name: "Session s1" });
    const hrefs = screen.getAllByRole("link").map((link) => link.getAttribute("href"));
    expect(hrefs).toContain("/sessions/s1");
    expect(hrefs).not.toContain("/sessions/s-123");
  });

  it("came from: shows no session for a malformed id", async () => {
    open({ type: "learning", session: "bad id!" });

    const section = await origin();
    expect(await within(section).findByText(NOTHING)).toBeInTheDocument();
    expect(within(section).queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Frontmatter" })).toHaveTextContent("session: bad id!");
  });

  it("came from: says No provenance recorded for this note.", async () => {
    open({ type: "index" });

    const section = await origin();
    expect(await within(section).findByText(NOTHING)).toBeInTheDocument();
    expect(within(section).queryByRole("term")).not.toBeInTheDocument();
  });

  it("came from: never shows effect words or session counts", async () => {
    const cases: [BrainNote["frontmatter"], Learning[]][] = [
      [{ provenance: "agent", sources: ["a", "b"] }, [accepted()]],
      [{ session: "s-123" }, []],
      [{ session: "bad id!" }, []],
      [{}, []],
      [{ provenance: "human" }, [accepted({ source_session_id: null, decided_by: null })]],
    ];
    for (const [frontmatter, learnings] of cases) {
      const view = open(frontmatter, aPage(learnings));
      const section = await origin();
      await vi.waitFor(() => {
        expect(section).not.toHaveAttribute("aria-busy");
      });
      const text = section.textContent;
      expect(text).not.toMatch(/effect|impact|fixed|improved|since/i);
      expect(text).not.toMatch(/\d+\s+sessions?/i);
      view.unmount();
    }
  });

  it("came from: says when a learning records no session or decider", async () => {
    open({}, aPage([accepted({ source_session_id: null, decided_by: null })]));

    const section = await origin();
    const line = await within(section).findByText(/^Accepted/);
    expect(line).toHaveTextContent("Accepted 11 Oct 2026 · no source session recorded");
    expect(within(section).queryByRole("link", { name: /^Session/ })).not.toBeInTheDocument();
  });

  it("came from: shows the first 5 sources, then all of them on demand", async () => {
    const sources = ["s1.md", "s2.md", "s3.md", "s4.md", "s5.md", "s6.md", "s7.md"];
    open({ sources });

    const section = await origin();
    expect(within(section).getByText("s5.md")).toBeInTheDocument();
    expect(within(section).queryByText("s6.md")).not.toBeInTheDocument();
    const more = within(section).getByRole("button", { name: "Show all 7 sources" });

    await userEvent.click(more);

    expect(within(section).getByText("s7.md")).toBeInTheDocument();
    expect(more).toHaveTextContent("Show the first 5");
    expect(more).toHaveFocus();
  });

  it("came from: shows a single source, the provenance as text when unknown", async () => {
    open({ provenance: "a scribe", sources: "one paper" });

    const section = await origin();
    expect(within(section).getByText("a scribe")).toBeInTheDocument();
    expect(within(section).getByText("one paper")).toBeInTheDocument();
  });

  it("came from: labels external content", async () => {
    open({ provenance: "agent-from-external" });

    const section = await origin();
    expect(within(section).getByText("agent-from-external")).toBeInTheDocument();
    expect(within(section).getByText(/External content/)).toBeInTheDocument();
  });

  it("came from: says the 10 newest are shown when more learnings name the note", async () => {
    open({}, aPage([accepted()], { next_cursor: "c2" }));

    const section = await origin();
    expect(
      await within(section).findByText("More learnings name this note; the 10 newest are shown."),
    ).toBeInTheDocument();
  });

  it("came from: says the learnings failed with Try again, the provenance still shown", async () => {
    let calls = 0;
    open({ provenance: "agent" }, () => {
      calls += 1;
      return calls === 1 ? aProblem({ status: 503, title: "Busy" }) : aPage([accepted()]);
    });

    const section = await origin();
    const problem = await within(section).findByRole("alert");
    expect(problem).toHaveTextContent("Could not load the learnings for this note.");
    expect(within(section).getByText("agent")).toBeInTheDocument();
    expect(within(section).queryByText(NOTHING)).not.toBeInTheDocument();

    await userEvent.click(within(problem).getByRole("button", { name: "Try again" }));

    expect(
      await within(section).findByRole("link", { name: "Run the screen a11y tests before the PR" }),
    ).toBeInTheDocument();
  });

  it("came from: the header button moves focus to the section", async () => {
    open({ provenance: "agent" });

    await userEvent.click(await screen.findByRole("button", { name: "Where it came from" }));

    expect(within(await origin()).getByRole("heading", { level: 2, name: ORIGIN })).toHaveFocus();
  });

  it("came from: shows neither section nor jump for a missing note", async () => {
    open({}, aPage([]), { [NOTE]: aProblem({ status: 404, title: "Not found" }) });

    expect(await screen.findByText("No note index.md in the agent-hub brain.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: ORIGIN })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /^Linked from/ })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^(Where it came from|Linked from)/ }),
    ).not.toBeInTheDocument();
  });

  it("came from has no serious a11y violations (a11y)", async () => {
    const full = open(
      { provenance: "agent", sources: ["a", "b"] },
      aPage([
        accepted(),
        accepted({ id: "l-2", state: "accepted_pr_open", source_session_id: "s2" }),
      ]),
    );
    await within(await origin()).findByRole("link", { name: "Session s1" });
    expect(await seriousViolations(full.container)).toEqual([]);
    full.unmount();

    const session = open({ session: "s-123" });
    await within(await origin()).findByRole("link", { name: "Session s-123" });
    expect(await seriousViolations(session.container)).toEqual([]);
    session.unmount();

    const none = open({});
    await within(await origin()).findByText(NOTHING);
    expect(await seriousViolations(none.container)).toEqual([]);
  });
});
