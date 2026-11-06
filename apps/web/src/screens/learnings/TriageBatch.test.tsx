import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aProblem, renderWithApi } from "../../testing/builders";
import { stageDecision } from "./staged";
import { TriageBatchBar } from "./TriageBatch";

const BATCH = "POST /api/v1/learnings/decisions";
const RESULT = {
  pr_url: "https://github.com/acme/demo-hub/pull/21",
  branch: "demo/learning-triage-20261029-120000",
  decided: [
    { learning_id: "l1", state: "accepted_pr_open" },
    { learning_id: "l2", state: "rejected_pr_open" },
  ],
};

function markTwo() {
  stageDecision("l1", {
    action: "accept",
    project: "demo",
    title: "Run the gate first",
    target: "learnings/",
  });
  stageDecision("l2", { action: "reject", project: "demo", title: "Noise", reason: "Duplicate" });
}

function openBar(routes = {}) {
  const onSelect = vi.fn();
  const result = renderWithApi(<TriageBatchBar onSelect={onSelect} />, { routes });
  return { ...result, onSelect };
}

describe("TriageBatchBar", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("shows nothing while no learning is marked", () => {
    openBar();

    expect(screen.queryByRole("region", { name: "Marked learnings" })).toBeNull();
  });

  it("counts the marked learnings by decision", () => {
    markTwo();
    openBar();

    const bar = screen.getByRole("region", { name: "Marked learnings" });
    expect(bar).toHaveTextContent("2 marked");
    expect(bar).toHaveTextContent("1 accept · 1 reject");
  });

  it("opens one pull request with every marked learning, then clears the marks", async () => {
    markTwo();
    const { requests } = openBar({ [BATCH]: RESULT });

    await userEvent.click(screen.getByRole("button", { name: "Review and open PR" }));
    const dialog = screen.getByRole("dialog", { name: "Open the triage pull request" });
    expect(within(dialog).getByText("Run the gate first")).toBeInTheDocument();
    expect(within(dialog).getByText("Duplicate")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Open pull request" }));

    const opened = await within(dialog).findByRole("status");
    expect(opened).toHaveTextContent("Pull request opened for demo · 2 learnings");
    expect(within(opened).getByRole("link", { name: /pull\/21/ })).toHaveAttribute(
      "href",
      RESULT.pr_url,
    );
    const posts = requests.filter((r) => r.method === "POST");
    expect(posts).toHaveLength(1);
    expect(await posts[0]?.json()).toEqual({
      decisions: [
        { learning_id: "l1", action: "accept", target: "learnings/", reason: "" },
        { learning_id: "l2", action: "reject", target: "", reason: "Duplicate" },
      ],
    });
    expect(window.localStorage.getItem("ah.learning.staged")).toBeNull();
    expect(screen.queryByRole("region", { name: "Marked learnings" })).toBeNull();
  });

  it("sends an accept's edited note body", async () => {
    stageDecision("l1", { action: "accept", project: "demo", title: "Gate", target: "learnings/" });
    window.localStorage.setItem(
      "ah.learning.draft.l1",
      JSON.stringify({ body: "# Edited\n", base: "# Original\n" }),
    );
    const { requests } = openBar({ [BATCH]: RESULT });

    await userEvent.click(screen.getByRole("button", { name: "Review and open PR" }));
    await userEvent.click(screen.getByRole("button", { name: "Open pull request" }));
    await screen.findByText(/Pull request opened/);

    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({
      decisions: [
        {
          learning_id: "l1",
          action: "accept",
          target: "learnings/",
          reason: "",
          note_body: "# Edited\n",
        },
      ],
    });
    expect(window.localStorage.getItem("ah.learning.draft.l1")).toBeNull();
  });

  it("keeps the marks and names the conflict when the pull request is refused", async () => {
    markTwo();
    openBar({
      [BATCH]: aProblem({ status: 409, title: "Conflict", detail: "Learning already rejected" }),
    });

    await userEvent.click(screen.getByRole("button", { name: "Review and open PR" }));
    await userEvent.click(screen.getByRole("button", { name: "Open pull request" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Learning already rejected");
    expect(window.localStorage.getItem("ah.learning.staged")).not.toBeNull();
  });

  it("unmarks one learning from the dialog", async () => {
    markTwo();
    openBar();

    await userEvent.click(screen.getByRole("button", { name: "Review and open PR" }));
    const dialog = screen.getByRole("dialog");
    const [first] = within(dialog).getAllByRole("button", { name: "Unmark" });
    if (!first) throw new Error("no Unmark button");
    await userEvent.click(first);

    expect(within(dialog).queryByText("Run the gate first")).toBeNull();
    expect(screen.getByRole("region", { name: "Marked learnings" })).toHaveTextContent("1 marked");
  });

  it("groups the marks by project in alphabetical order, one pull request each", async () => {
    stageDecision("o1", { action: "reject", project: "other", title: "Stale", reason: "Old" });
    markTwo();
    const { requests } = openBar({ [BATCH]: RESULT });

    await userEvent.click(screen.getByRole("button", { name: "Review and open PR" }));
    const dialog = screen.getByRole("dialog", { name: "Open the triage pull request" });
    const sends = within(dialog).getAllByRole("button", { name: "Open pull request" });
    expect(sends).toHaveLength(2);
    const blocks = sends.map((b) => b.closest(".ah-stack"));
    expect(blocks[0]).toHaveTextContent(/^demo/);
    expect(blocks[1]).toHaveTextContent(/^other/);
    const [, other] = sends;
    if (!other) throw new Error("no second block");
    await userEvent.click(other);

    await within(dialog).findByText(/Pull request opened for other/);
    const posts = requests.filter((r) => r.method === "POST");
    expect(posts).toHaveLength(1);
    expect(await posts[0]?.json()).toEqual({
      decisions: [{ learning_id: "o1", action: "reject", target: "", reason: "Old" }],
    });
  });

  it("refuses more than 50 marks of one project in one pull request", async () => {
    for (let n = 0; n < 51; n += 1) {
      stageDecision(`l${String(n)}`, {
        action: "reject",
        project: "demo",
        title: `Learning ${String(n)}`,
        reason: "Duplicate",
      });
    }
    openBar();

    await userEvent.click(screen.getByRole("button", { name: "Review and open PR" }));

    const send = screen.getByRole("button", { name: "Open pull request" });
    expect(send).toBeDisabled();
    expect(send).toHaveAttribute("title", "At most 50 per pull request");
  });

  it("keeps Tab inside the dialog and closes it with Escape", async () => {
    markTwo();
    openBar();

    await userEvent.click(screen.getByRole("button", { name: "Review and open PR" }));
    const dialog = screen.getByRole("dialog");
    const send = within(dialog).getByRole("button", { name: "Open pull request" });
    expect(send).toHaveFocus();
    within(dialog).getByRole("button", { name: "Close" }).focus();
    await userEvent.tab();
    expect(send).toHaveFocus();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("has no serious a11y violations with the dialog open (a11y)", async () => {
    markTwo();
    const { container } = openBar();

    await userEvent.click(screen.getByRole("button", { name: "Review and open PR" }));

    expect(await seriousViolations(container)).toEqual([]);
  });
});
