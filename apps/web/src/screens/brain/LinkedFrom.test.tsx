import { readFileSync } from "node:fs";

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aBacklink,
  aBrainNote,
  aBrainTree,
  aNoteBacklinks,
  aPage,
  aProblem,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { BrainScreen } from "./index";

const TREE = "/api/v1/projects/agent-hub/brain";
const NOTE = "/api/v1/projects/agent-hub/brain/note";
const BACKLINKS = "/api/v1/projects/agent-hub/brain/backlinks";
const LEARNINGS = "/api/v1/learnings";
const route = "projects/:project/brain/*";

const SLOW =
  "Reading the hub's notes to find the links. A first read after an update can take a few seconds.";

/** `index.md` of project agent-hub on the Brain screen, its backlinks answered by `backlinks`. */
function open(
  backlinks: ApiRoutes[string],
  routes: ApiRoutes = {},
  path = "/projects/agent-hub/brain",
) {
  return renderWithApi(<BrainScreen />, {
    routes: {
      [TREE]: aBrainTree(),
      [NOTE]: aBrainNote(),
      [LEARNINGS]: aPage([]),
      [BACKLINKS]: backlinks,
      ...routes,
    },
    path,
    route,
  });
}

function twoSources() {
  return aNoteBacklinks({
    items: [
      aBacklink(),
      aBacklink({ path: "demo-api/docs/guide.md", kind: "doc", title: "Repo guide" }),
    ],
  });
}

function linkedFrom(count?: string): Promise<HTMLElement> {
  const name = count === undefined ? "Linked from" : `Linked from · ${count}`;
  return screen.findByRole("region", { name });
}

describe("BrainScreen Linked from", () => {
  const scroll = vi.fn();
  beforeEach(() => {
    scroll.mockClear();
    Element.prototype.scrollIntoView = scroll;
  });

  it("linked from: lists two sources, the brain one a link (AC-393.13)", async () => {
    const { requests } = open(twoSources());

    const section = await linkedFrom("2");
    expect(within(section).getByRole("link", { name: "Cleanup after merge" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/brain/playbooks/cleanup.md",
    );
    expect(within(section).getAllByRole("link")).toHaveLength(1);
    const guide = within(section).getByText("Repo guide").closest("li");
    expect(guide).toHaveTextContent("demo-api/docs/guide.md");
    expect(guide).toHaveTextContent("doc · repo doc, not opened here");
    expect(within(guide as HTMLElement).getByRole("tooltip")).toHaveTextContent(
      "Repo docs are not opened in the app",
    );
    const asked = requests.find((r) => new URL(r.url).pathname === BACKLINKS);
    expect(new URL(asked?.url ?? "").searchParams.get("path")).toBe("index.md");
  });

  it("linked from: says No note links here.", async () => {
    open(aNoteBacklinks());

    const section = await linkedFrom("0");
    expect(within(section).getByText("No note links here.")).toBeInTheDocument();
    expect(within(section).queryByRole("list")).not.toBeInTheDocument();
  });

  it("linked from: says and 30 more over 100", async () => {
    const items = Array.from({ length: 100 }, (_, i) =>
      aBacklink({
        path: `brain/notes/n${String(i).padStart(3, "0")}.md`,
        title: `Note ${String(i)}`,
      }),
    );
    open(aNoteBacklinks({ items, total: 130 }));

    const section = await linkedFrom("130");
    expect(within(section).getAllByRole("link")).toHaveLength(100);
    expect(within(section).getByText("and 30 more")).not.toHaveAttribute("href");
  });

  it("linked from: says how many more link here than are listed", async () => {
    open(aNoteBacklinks({ items: [aBacklink(), aBacklink({ path: "brain/b.md" })], total: 5 }));

    const section = await linkedFrom("5");
    expect(within(section).getByText("and 3 more")).toBeInTheDocument();
  });

  it("linked from: keeps the Brain search's query on a source link", async () => {
    open(twoSources(), {}, "/projects/agent-hub/brain?q=cleanup");

    const section = await linkedFrom("2");
    expect(within(section).getByRole("link", { name: "Cleanup after merge" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/brain/playbooks/cleanup.md?q=cleanup",
    );
  });

  it("linked from: shows the failure with Try again, the note still shown", async () => {
    let calls = 0;
    open(() => {
      calls += 1;
      return calls === 1
        ? aProblem({
            status: 502,
            title: "Could not read the links of this hub",
            detail: "brain: git exited with 128: fatal: not a git repository",
          })
        : twoSources();
    });

    const section = await linkedFrom();
    const problem = await within(section).findByRole("alert");
    expect(problem).toHaveTextContent("Could not read the links of this hub");
    expect(problem).toHaveTextContent("brain: git exited with 128: fatal: not a git repository");
    const note = screen.getByRole("article");
    expect(within(note).getByRole("heading", { level: 1, name: "Brain" })).toBeInTheDocument();

    await userEvent.click(within(problem).getByRole("button", { name: "Try again" }));

    const answered = await linkedFrom("2");
    expect(within(answered).getByRole("link", { name: "Cleanup after merge" })).toBeVisible();
  });

  it("linked from: shows a source the app cannot open as text (AM-8)", async () => {
    open(
      aNoteBacklinks({
        items: [aBacklink({ path: "brain/.hidden/x.md", kind: "playbook", title: "Hidden note" })],
      }),
    );

    const section = await linkedFrom("1");
    expect(within(section).getByText("Hidden note")).toBeInTheDocument();
    expect(within(section).queryByRole("link")).not.toBeInTheDocument();
    expect(within(section).getByTitle("brain/.hidden/x.md")).toBeInTheDocument();
    // The reason in the tooltip, and the same words as a repo doc on the kind line (K5, H9).
    expect(within(section).getByRole("tooltip")).toHaveTextContent(
      "The app does not open notes at this path (not a .md file, a hidden name, under auto/, or too long or deep)",
    );
    const row = within(section).getByText("Hidden note").closest("li");
    expect(row?.querySelector(".ah-know-kind")).toHaveTextContent(/^playbook · not opened here$/);
    expect(row).toHaveAccessibleDescription(/^The app does not open notes at this path/);
  });

  it("linked from: lights up only the rows that open a note on hover", () => {
    // Read as a file: Vitest runs from apps/web and jsdom applies no stylesheet.
    const css = readFileSync("src/screens/brain/Brain.css", "utf8");
    const hovers = [...css.matchAll(/^([^{}\n]*\.ah-know-row[^{}\n]*:hover)\s*\{/gm)].map(
      (match) => match[1],
    );
    expect(hovers).toEqual([":where(a).ah-know-row:hover"]);
  });

  it("linked from: shows skeletons, then says the first read can take a few seconds", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    try {
      open("pending");
      let section: HTMLElement | null = null;
      for (let i = 0; i < 50 && section === null; i += 1) {
        await vi.advanceTimersByTimeAsync(0);
        section = screen.queryByRole("region", { name: "Linked from" });
      }
      if (section === null) throw new Error("no Linked from section");
      expect(section).toHaveAttribute("aria-busy", "true");

      await vi.advanceTimersByTimeAsync(1_999);
      expect(section.querySelector(".ah-skel")).not.toBeNull();
      expect(within(section).queryByText(SLOW)).not.toBeInTheDocument();
      await vi.advanceTimersByTimeAsync(1);
      expect(within(section).getByText(SLOW)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("linked from: the header button names the count and moves focus to the section", async () => {
    open(twoSources());

    const jump = await screen.findByRole("button", { name: "Linked from · 2" });
    expect(jump).toHaveTextContent("Linked from · 2");
    await userEvent.click(jump);

    const heading = within(await linkedFrom("2")).getByRole("heading", { level: 2 });
    expect(heading).toHaveFocus();
    expect(scroll.mock.contexts).toContain(heading);
  });

  it("linked from: the header buttons' names contain their visible text (WCAG 2.5.3)", async () => {
    const { container } = open(twoSources());
    await linkedFrom("2");

    const jumps = [...container.querySelectorAll<HTMLElement>(".ah-brain-jumps button")];
    expect(jumps.map((jump) => jump.textContent)).toEqual([
      "Where it came from",
      "Linked from · 2",
    ]);
    for (const jump of jumps) {
      const visible = jump.textContent.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      expect(jump).toHaveAccessibleName(new RegExp(visible));
    }
  });

  it("linked from: opens a source note and moves focus to its path line", async () => {
    const { router } = open(twoSources());

    await userEvent.click(
      within(await linkedFrom("2")).getByRole("link", { name: "Cleanup after merge" }),
    );

    expect(router.state.location.pathname).toBe("/projects/agent-hub/brain/playbooks/cleanup.md");
    await vi.waitFor(() => {
      expect(
        screen.getByText("brain/playbooks/cleanup.md", { selector: "#brain-note-path" }),
      ).toHaveFocus();
    });
  });

  it("linked from has no serious a11y violations (a11y)", async () => {
    const items = open(twoSources());
    await linkedFrom("2");
    expect(await seriousViolations(items.container)).toEqual([]);
    items.unmount();

    const none = open(aNoteBacklinks());
    await screen.findByText("No note links here.");
    expect(await seriousViolations(none.container)).toEqual([]);
    none.unmount();

    const failed = open(aProblem({ status: 502, title: "Could not read the links of this hub" }));
    await within(await linkedFrom()).findByRole("alert");
    expect(await seriousViolations(failed.container)).toEqual([]);
  });
});
