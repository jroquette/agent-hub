import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aBrainNote,
  aLearning,
  aLearningActionResult,
  aLearningDetail,
  anId,
  aProblem,
  aProjectDetail,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { LearningDetail } from "./LearningDetail";

const ID = anId(9, "0192cccc");
const DETAIL = `/api/v1/learnings/${ID}`;
const ACCEPT = `POST /api/v1/learnings/${ID}/accept`;
const REJECT = `POST /api/v1/learnings/${ID}/reject`;
const CONFIRM_TEXT =
  "This opens a pull request in agent-hub-hub. Nothing changes in the brain until you merge it.";

const base: ApiRoutes = {
  [DETAIL]: aLearningDetail(),
  "/api/v1/projects/agent-hub": aProjectDetail({ hub_repo: "agent-hub-hub" }),
};

function open(extra: ApiRoutes = {}, onDecide = vi.fn()) {
  const result = renderWithApi(
    <LearningDetail id={ID} row={aLearning()} now={Date.now()} onDecide={onDecide} />,
    { routes: { ...base, ...extra }, path: "/knowledge/learnings" },
  );
  return { ...result, onDecide };
}

async function region() {
  const detail = await screen.findByRole("region", { name: "Proposal" });
  await within(detail).findByRole("region", { name: "Note" });
  return detail;
}

describe("LearningDetail", () => {
  it("renders the note safely with its project, state and source moment", async () => {
    open({
      [DETAIL]: aLearningDetail({
        note: aBrainNote({
          path: "_inbox/web-gates.md",
          markdown: "## Why\n\nRun `npm ci` first.\n\n<script>alert(1)</script>\n",
        }),
      }),
    });

    const detail = await screen.findByRole("region", { name: "Proposal" });
    const note = await within(detail).findByRole("region", { name: "Note" });
    expect(within(note).getByRole("heading", { name: "Why" })).toBeInTheDocument();
    expect(within(note).getByText("npm ci").tagName).toBe("CODE");
    expect(within(note).getByText("<script>alert(1)</script>")).toBeInTheDocument();
    expect(note.querySelector("script")).toBeNull();
    expect(within(detail).getByText("agent-hub")).toBeInTheDocument();
    expect(within(detail).getByText("Proposed")).toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: /Open at that moment/ })).toHaveAttribute(
      "href",
      `/sessions/${anId(1, "5091b986")}?tab=timeline&event=${anId(10, "0192aaaa")}`,
    );
  });

  it("shows the note's type, repos and provenance from its frontmatter", async () => {
    open({
      [DETAIL]: aLearningDetail({
        provenance: null,
        note: aBrainNote({
          frontmatter: {
            type: "learning",
            repos: ["Tipple_API", "tipple-ui"],
            provenance: "agent-from-code",
            sources: ["x.py:1"],
          },
        }),
      }),
    });

    const detail = await region();
    expect(within(detail).getByText("learning")).toBeInTheDocument();
    expect(within(detail).getByText("Tipple_API, tipple-ui")).toBeInTheDocument();
    expect(within(detail).getByText("agent-from-code")).toBeInTheDocument();
  });

  it("explains a note missing from the checkout and blocks the decision", async () => {
    open({
      [DETAIL]: aLearningDetail({
        note: null,
        note_path: "brain/_inbox/gone.md",
        note_unavailable: "Note not in the hub checkout",
        actions_unavailable: "Note not in the hub checkout",
      }),
    });

    const detail = await region();
    expect(within(detail).getByText(/never pushed/)).toBeInTheDocument();
    expect(within(detail).queryByText(/unedited/)).toBeNull();
    expect(within(detail).getByText("Cannot be decided here.")).toBeInTheDocument();
    expect(within(detail).getByRole("button", { name: "Accept" })).toBeDisabled();
  });

  it("opens brain links of the note inside the app", async () => {
    const { router } = open({
      [DETAIL]: aLearningDetail({
        note: aBrainNote({
          path: "_inbox/web-gates.md",
          markdown: "See [the gates](../playbooks/gates.md#web).\n",
        }),
      }),
    });

    const link = await screen.findByRole("link", { name: "the gates" });
    expect(link).toHaveAttribute("href", "/projects/agent-hub/brain/playbooks/gates.md#web");
    await userEvent.click(link);

    expect(router.state.location.pathname).toBe("/projects/agent-hub/brain/playbooks/gates.md");
    expect(router.state.location.hash).toBe("#web");
  });

  it("says why the note is unavailable", async () => {
    open({
      [DETAIL]: aLearningDetail({ note: null, note_unavailable: "Note not in the hub checkout" }),
    });

    const detail = await region();
    expect(within(detail).getByText("Note not in the hub checkout")).toBeInTheDocument();
  });

  it("shows the list's summary while the detail loads", () => {
    open({ [DETAIL]: "pending" });

    const detail = screen.getByRole("region", { name: "Proposal" });
    expect(
      within(detail).getByText("Run `npm ci` in apps/web before the web gates."),
    ).toBeInTheDocument();
  });

  it("shows the problem when the learning cannot be read", async () => {
    open({ [DETAIL]: aProblem({ status: 404, title: "Not found", detail: "No such learning." }) });

    expect(await screen.findByRole("alert")).toHaveTextContent("No such learning.");
  });

  it("offers the target choices with the suggested folder by default", async () => {
    open();

    const detail = await region();
    const target = within(detail).getByRole("combobox", { name: "Target in brain/" });
    expect(target).toHaveValue("learnings/");
    const options = [...((target as HTMLInputElement).list?.options ?? [])].map((o) => o.value);
    expect(options).toEqual(["learnings/", "playbooks/"]);
  });

  it("accepts to the edited target through a confirmation, then links the pull request", async () => {
    const { requests, onDecide } = open({ [ACCEPT]: aLearningActionResult() });
    const detail = await region();
    const target = within(detail).getByRole("combobox", { name: "Target in brain/" });
    await userEvent.clear(target);
    await userEvent.type(target, "learnings/gotchas/web-gates.md");

    await userEvent.click(within(detail).getByRole("button", { name: "Accept" }));
    const dialog = screen.getByRole("dialog", { name: "Accept this learning?" });
    expect(dialog).toHaveAccessibleDescription(CONFIRM_TEXT);
    expect(within(dialog).getByText("brain/learnings/gotchas/web-gates.md")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Open pull request" }));

    const done = await screen.findByRole("status");
    expect(done).toHaveTextContent("Pull request opened");
    expect(within(done).getByRole("link", { name: /pull\/12/ })).toHaveAttribute(
      "href",
      "https://github.com/acme/agent-hub-hub/pull/12",
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    const post = requests.find((r) => r.method === "POST");
    expect(post?.headers.get("content-type")).toContain("application/json");
    expect(await post?.json()).toEqual({ target: "learnings/gotchas/web-gates.md" });
    expect(onDecide).toHaveBeenCalledWith(ID);
  });

  describe("editing the note", () => {
    beforeEach(() => {
      window.localStorage.clear();
    });

    it("accepts the edited body in the same pull request", async () => {
      const { requests } = open({ [ACCEPT]: aLearningActionResult() });
      const detail = await region();

      await userEvent.click(within(detail).getByRole("button", { name: "Edit note" }));
      const field = within(detail).getByRole("textbox", { name: "Note body" });
      await userEvent.clear(field);
      await userEvent.type(field, "# Gates{enter}{enter}Run the web gate first.");
      await userEvent.click(within(detail).getByRole("button", { name: "Preview" }));
      expect(within(detail).getByRole("heading", { name: "Gates" })).toBeInTheDocument();
      await userEvent.click(within(detail).getByRole("button", { name: "Done editing" }));
      expect(within(detail).getByText("Edited here.")).toBeInTheDocument();

      await userEvent.click(within(detail).getByRole("button", { name: "Accept" }));
      const dialog = screen.getByRole("dialog", { name: "Accept this learning?" });
      expect(
        within(dialog).getByText("Writes the note as you edited it, in the same commit"),
      ).toBeInTheDocument();
      await userEvent.click(within(dialog).getByRole("button", { name: "Open pull request" }));

      await screen.findByText("Pull request opened");
      const post = requests.find((r) => r.method === "POST");
      expect(await post?.json()).toEqual({
        target: "learnings/",
        note_body: "# Gates\n\nRun the web gate first.",
      });
      expect(window.localStorage.getItem(`ah.learning.draft.${ID}`)).toBeNull();
    });

    it("keeps the edit across a reload and discards it after a confirm", async () => {
      window.localStorage.setItem(
        `ah.learning.draft.${ID}`,
        JSON.stringify({ body: "# Kept\n", base: aLearningDetail().note?.markdown ?? "" }),
      );
      open();
      const detail = await region();

      expect(within(detail).getByRole("heading", { name: "Kept" })).toBeInTheDocument();
      await userEvent.click(within(detail).getByRole("button", { name: "Discard edits" }));
      expect(within(detail).getByText("Discard your edits?")).toBeInTheDocument();
      await userEvent.click(within(detail).getByRole("button", { name: "Discard edits" }));

      expect(within(detail).queryByRole("heading", { name: "Kept" })).toBeNull();
      expect(within(detail).getByText(/unedited/)).toBeInTheDocument();
    });

    it("warns when the note changed in the hub since the edit started", async () => {
      window.localStorage.setItem(
        `ah.learning.draft.${ID}`,
        JSON.stringify({ body: "# Mine\n", base: "# An older hub version\n" }),
      );
      open();
      const detail = await region();

      expect(
        within(detail).getByText("The note changed in the hub since you edited it."),
      ).toBeInTheDocument();
    });

    it("offers no edit when the learning cannot be decided", async () => {
      open({ [DETAIL]: aLearningDetail({ actions_unavailable: "The hub is read-only" }) });
      const detail = await region();

      expect(within(detail).queryByRole("button", { name: "Edit note" })).toBeNull();
    });
  });

  it("rejects with a reason through a confirmation", async () => {
    const { requests } = open({
      [REJECT]: aLearningActionResult({ state: "rejected_pr_open" }),
    });
    const detail = await region();

    await userEvent.click(within(detail).getByRole("button", { name: "Reject" }));
    const dialog = screen.getByRole("dialog", { name: "Reject this learning?" });
    expect(dialog).toHaveAccessibleDescription(CONFIRM_TEXT);
    await userEvent.type(within(dialog).getByRole("textbox", { name: /Reason/ }), "Duplicate");
    await userEvent.click(within(dialog).getByRole("button", { name: "Open pull request" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Pull request opened");
    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({ reason: "Duplicate" });
  });

  it("keeps the dialog open with a conflict's reason", async () => {
    open({
      [ACCEPT]: aProblem({
        status: 409,
        title: "Conflict",
        detail: "Target already exists in the brain",
      }),
    });
    const detail = await region();

    await userEvent.click(within(detail).getByRole("button", { name: "Accept" }));
    await userEvent.click(screen.getByRole("button", { name: "Open pull request" }));

    const alert = await within(screen.getByRole("dialog")).findByRole("alert");
    expect(alert).toHaveTextContent("Target already exists in the brain");
  });

  it("shows a failed pull request as retryable", async () => {
    open({
      [ACCEPT]: aProblem({ status: 502, title: "Could not open the pull request" }),
    });
    const detail = await region();

    await userEvent.click(within(detail).getByRole("button", { name: "Accept" }));
    await userEvent.click(screen.getByRole("button", { name: "Open pull request" }));

    const alert = await within(screen.getByRole("dialog")).findByRole("alert");
    expect(alert).toHaveTextContent("Could not open the pull request");
    expect(alert).toHaveTextContent("Try again.");
    expect(screen.getByRole("button", { name: "Open pull request" })).toBeEnabled();
  });

  it("shows progress while the pull request opens", async () => {
    open({ [ACCEPT]: "pending" });
    const detail = await region();

    await userEvent.click(within(detail).getByRole("button", { name: "Accept" }));
    await userEvent.click(screen.getByRole("button", { name: "Open pull request" }));

    expect(await screen.findByRole("button", { name: "Opening pull request…" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Opening the pull request");
  });

  it("disables accept and reject with the read-only reason (read-only)", async () => {
    open({ [DETAIL]: aLearningDetail({ actions_unavailable: "Hub is read-only here" }) });
    const detail = await region();

    for (const name of ["Accept", "Reject"]) {
      const button = within(detail).getByRole("button", { name });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("title", "Hub is read-only here");
    }
    expect(within(detail).getByText("Hub is read-only here")).toBeInTheDocument();
    expect(within(detail).queryByRole("combobox")).toBeNull();
  });

  it("tags only Snooze as Phase 3", async () => {
    open();
    const detail = await region();

    for (const name of ["Accept", "Reject"]) {
      const button = within(detail).getByRole("button", { name });
      expect(button).toBeEnabled();
      expect(within(button).queryByText("P3")).toBeNull();
    }
    const snooze = within(detail).getByRole("button", { name: /^Snooze/ });
    expect(snooze).toBeDisabled();
    expect(within(snooze).getByText("P3")).toHaveClass("ah-phase");
  });

  it.each([
    ["accepted_pr_open", "Accepted · PR open"],
    ["rejected_pr_open", "Rejected · PR open"],
  ] as const)("shows the %s badge, its pull request and no actions", async (state, label) => {
    open({
      [DETAIL]: aLearningDetail({
        state,
        pr_url: "https://github.com/acme/agent-hub-hub/pull/7",
      }),
    });
    const detail = await region();

    expect(within(detail).getByText(label)).toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: /pull\/7/ })).toHaveAttribute(
      "href",
      "https://github.com/acme/agent-hub-hub/pull/7",
    );
    expect(within(detail).getByRole("button", { name: "Accept" })).toBeDisabled();
    expect(
      within(detail).getAllByText("A pull request for this learning is already open").length,
    ).toBeGreaterThan(0);
  });

  it.each([
    ["in_brain", "In brain"],
    ["archived", "Archived"],
  ] as const)("shows the %s badge", async (state, label) => {
    open({ [DETAIL]: aLearningDetail({ state, brain_path: "learnings/web-gates.md" }) });
    const detail = await region();

    expect(within(detail).getByText(label)).toBeInTheDocument();
    expect(within(detail).getByRole("button", { name: "Reject" })).toBeDisabled();
  });

  it("has no serious a11y violations with the dialog open (a11y)", async () => {
    const { container } = open({ [ACCEPT]: aProblem({ status: 409, title: "Conflict" }) });
    const detail = await region();
    await userEvent.click(within(detail).getByRole("button", { name: "Reject" }));
    await userEvent.type(screen.getByRole("textbox", { name: /Reason/ }), "Duplicate");

    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
    expect(await seriousViolations(container)).toEqual([]);
  });
});
