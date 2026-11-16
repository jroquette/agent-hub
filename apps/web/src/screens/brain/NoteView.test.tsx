import { readFileSync } from "node:fs";

import { screen, waitFor, within } from "@testing-library/react";
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

  it("AC-PG-12.1 shows values up to 48 characters as single-line chips with the full text on hover", async () => {
    const exact = "x".repeat(48);
    open({ [NOTE]: aBrainNote({ frontmatter: { owner: exact, tags: ["a", "b"] } }) });

    const chips = within(await screen.findByRole("list", { name: "Frontmatter" })).getAllByRole(
      "listitem",
    );
    expect(chips).toHaveLength(2);
    expect(chips[0]).toHaveClass("ah-fm-chip");
    expect(chips[0]).toHaveAttribute("title", exact);
    expect(chips[1]).toHaveAttribute("title", "a, b");
    expect(screen.queryByRole("definition")).not.toBeInTheDocument();
    // Read as a file: Vitest runs from apps/web and jsdom applies no stylesheet.
    const css = readFileSync("src/styles/bundle.css", "utf8");
    expect(css).toMatch(/\.ah-fm-chip\s*\{[^}]*white-space:\s*nowrap/);
    expect(css).toMatch(/\.ah-fm-chip\s*\{[^}]*overflow:\s*hidden/);
    expect(css).toMatch(/\.ah-fm-chip\s*\{[^}]*text-overflow:\s*ellipsis/);
  });

  it("AC-PG-12.2 lists values over 48 characters full-width between the chips and the body", async () => {
    const long = "y".repeat(49);
    const { container } = open({
      [NOTE]: aBrainNote({ frontmatter: { type: "index", summary: long } }),
    });

    await screen.findByRole("heading", { level: 1, name: "Brain" });
    const chips = screen.getByRole("list", { name: "Frontmatter" });
    expect(chips).toHaveTextContent("type: index");
    expect(chips).not.toHaveTextContent(long);
    const fields = container.querySelector('dl[aria-label="Frontmatter, long fields"]');
    expect(fields).not.toBeNull();
    expect(fields).toHaveClass("ah-fm-long");
    expect(within(fields as HTMLElement).getByRole("term")).toHaveTextContent("summary");
    expect(within(fields as HTMLElement).getByRole("definition")).toHaveTextContent(long);
    const heading = screen.getByRole("heading", { level: 1, name: "Brain" });
    expect(
      chips.compareDocumentPosition(fields as Node) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      (fields as Node).compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const css = readFileSync("src/styles/bundle.css", "utf8");
    expect(css).toMatch(/\.ah-fm-long dd\s*\{[^}]*overflow-wrap:\s*anywhere/);
  });

  it("AC-PG-12.2 shows only the long fields list when every value is over 48 characters", async () => {
    const { container } = open({
      [NOTE]: aBrainNote({ frontmatter: { summary: "z".repeat(60) } }),
    });

    await screen.findByRole("heading", { level: 1, name: "Brain" });
    expect(screen.queryByRole("list", { name: "Frontmatter" })).not.toBeInTheDocument();
    expect(container.querySelector('dl[aria-label="Frontmatter, long fields"]')).not.toBeNull();
  });

  it("hides the fields the Brain screen shows elsewhere", async () => {
    renderWithApi(
      <NoteView project="agent-hub" path="index.md" hiddenFields={["provenance", "sources"]} />,
      {
        routes: {
          [NOTE]: aBrainNote({
            frontmatter: { type: "learning", provenance: "agent", sources: ["a", "b"] },
          }),
        },
        path: "/here",
      },
    );

    const chips = await screen.findByRole("list", { name: "Frontmatter" });
    expect(chips).toHaveTextContent("type: learning");
    expect(chips).not.toHaveTextContent("provenance");
    expect(chips).not.toHaveTextContent("sources");
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
