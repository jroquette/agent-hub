import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aBrainNote, aProblem, renderWithApi, type ApiRoutes } from "../../testing/builders";
import { NoteView, fragmentOf } from "./NoteView";

const NOTE = "/api/v1/projects/agent-hub/brain/note";

function open(routes: ApiRoutes = {}, path = "/here", note = "index.md") {
  return renderWithApi(<NoteView project="agent-hub" path={note} />, {
    routes: { [NOTE]: aBrainNote(), ...routes },
    path,
  });
}

describe("NoteView", () => {
  const scroll = vi.fn();
  beforeEach(() => {
    Element.prototype.scrollIntoView = scroll;
  });
  afterEach(() => {
    scroll.mockClear();
  });

  it("renders the note and its frontmatter when it loads", async () => {
    const { requests } = open();

    expect(await screen.findByRole("heading", { level: 1, name: "Brain" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Frontmatter" })).toHaveTextContent(
      "last_verified: 2026-10-11",
    );
    expect(new URL(requests[0]?.url ?? "").searchParams.get("path")).toBe("index.md");
  });

  it("opens a linked note in the app when a brain link is clicked", async () => {
    const { router } = open();

    await userEvent.click(await screen.findByRole("link", { name: "decisions" }));

    expect(router.state.location.pathname).toBe("/projects/agent-hub/brain/decisions/index.md");
  });

  it("scrolls to the heading named by the URL anchor when the note loads", async () => {
    open(
      { [NOTE]: aBrainNote({ markdown: "# Brain\n\n## Open questions\n\nNone.\n" }) },
      "/here#open-questions",
    );

    await screen.findByRole("heading", { level: 2, name: "Open questions" });
    await waitFor(() => {
      expect(scroll).toHaveBeenCalled();
    });
    expect(scroll.mock.contexts[0]).toHaveAttribute("id", "md-open-questions");
  });

  it("says the note is missing when the API answers 404", async () => {
    open({ [NOTE]: aProblem({ status: 404, title: "Not found" }) }, "/here", "gone.md");

    expect(await screen.findByText("No note gone.md in the agent-hub brain.")).toBeInTheDocument();
  });

  it("explains a note too large to show when the API answers 413", async () => {
    open({ [NOTE]: aProblem({ status: 413, title: "Too large", detail: "Over 256 KiB." }) });

    expect(await screen.findByRole("alert")).toHaveTextContent("This note is too large to show");
  });

  it("offers Try again when the note cannot be read", async () => {
    open({ [NOTE]: aProblem({ status: 503, title: "Hub not readable" }) });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Hub not readable");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("warns and shows the whole file when the frontmatter cannot be read", async () => {
    open({
      [NOTE]: aBrainNote({
        frontmatter: {},
        frontmatter_problem: "unclosed frontmatter",
        markdown: "---\ntype: x\n\n# Brain\n",
      }),
    });

    expect(await screen.findByRole("status")).toHaveTextContent(
      "The frontmatter could not be read: unclosed frontmatter",
    );
    expect(screen.queryByRole("list", { name: "Frontmatter" })).not.toBeInTheDocument();
  });

  it.each([
    ["", null],
    ["#", null],
    ["#d3", "d3"],
    ["#open%20questions", "open questions"],
    ["#%E0%A4%A", null],
  ])("reads the fragment of %j as %j", (hash, fragment) => {
    expect(fragmentOf(hash)).toBe(fragment);
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = open();
    await screen.findByRole("heading", { level: 1, name: "Brain" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
