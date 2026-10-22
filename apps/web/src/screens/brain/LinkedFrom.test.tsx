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

/** `index.md` of project agent-hub on the Brain screen, its backlinks answered by `backlinks`. */
function open(backlinks: ApiRoutes[string], routes: ApiRoutes = {}) {
  return renderWithApi(<BrainScreen />, {
    routes: {
      [TREE]: aBrainTree(),
      [NOTE]: aBrainNote(),
      [LEARNINGS]: aPage([]),
      [BACKLINKS]: backlinks,
      ...routes,
    },
    path: "/projects/agent-hub/brain",
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
    expect(within(section).getByRole("tooltip")).toHaveTextContent(
      "This note is not opened in the app",
    );
  });

  it("linked from: shows skeletons, then says the first read can take a few seconds", async () => {
    open("pending");

    const section = await linkedFrom();
    expect(section).toHaveAttribute("aria-busy", "true");
    await vi.waitFor(() => {
      expect(section.querySelector(".ah-skel")).not.toBeNull();
    });
    expect(
      await within(section).findByText(
        "Reading the hub's notes to find the links. A first read after an update can take a few seconds.",
        {},
        { timeout: 3000 },
      ),
    ).toBeInTheDocument();
  });

  it("linked from: the header button names the count and moves focus to the section", async () => {
    open(twoSources());

    const jump = await screen.findByRole("button", { name: "Go to Linked from, 2 notes" });
    expect(jump).toHaveTextContent("Linked from · 2");
    await userEvent.click(jump);

    const heading = within(await linkedFrom("2")).getByRole("heading", { level: 2 });
    expect(heading).toHaveFocus();
    expect(scroll.mock.contexts).toContain(heading);
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
