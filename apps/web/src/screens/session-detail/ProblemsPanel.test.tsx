import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aSessionProblem, aSessionProblems, anActor, anId, at } from "../../testing/builders";
import { ProblemBadge, ProblemsPanel, kindCounts, problemCounts } from "./ProblemsPanel";

const FAILED = anId(7, "0192aaaa");
const DENIED = anId(9, "0192aaaa");

function problems() {
  return aSessionProblems({
    summary: [
      { event_id: FAILED, text: "Needs you: make check-fast failed (1 failed, 12 passed)" },
      { event_id: DENIED, text: "The guard blocked git push; the agent continued" },
    ],
    items: [
      aSessionProblem({ event_id: FAILED, at: at(420) }),
      aSessionProblem({
        event_id: DENIED,
        at: at(480),
        kind: "guard_denied",
        tool: "Bash",
        where: "git push origin main",
        message: "rule no-push-main",
        resolution: "agent_continued",
        actor: anActor({ kind: "subagent", agent_id: "s1", type: "Explore" }),
      }),
    ],
  });
}

function renderPanel(onOpen = vi.fn()) {
  return render(
    <ProblemsPanel problems={problems()} timeOf={(at) => at.slice(11, 19)} onOpen={onOpen} />,
  );
}

describe("ProblemsPanel what-went-wrong", () => {
  it("lists the summary and each problem's kind, tool, where, message, time, actor and status when the session has problems", () => {
    renderPanel();

    const panel = screen.getByRole("region", { name: "What went wrong" });
    expect(within(panel).getByText("1 needs you · 1 handled by the agent")).toBeInTheDocument();
    const summary = within(panel).getByRole("list", { name: "Summary" });
    expect(
      within(summary)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      expect.stringContaining("Needs you: make check-fast failed (1 failed, 12 passed)"),
      expect.stringContaining("The guard blocked git push; the agent continued"),
    ]);

    const attention = within(panel).getByRole("list", { name: "Needs attention" });
    const [failed] = within(attention).getAllByRole("listitem");
    if (!failed) throw new Error("one problem needing the owner expected");
    for (const text of [
      "Command failed",
      "Bash",
      "make check-fast",
      "1 failed, 12 passed",
      "14:07:00",
      "Main agent",
      "Needs you",
    ]) {
      expect(within(failed).getByText(text)).toBeInTheDocument();
    }
    expect(within(panel).queryByRole("list", { name: "Handled" })).not.toBeInTheDocument();

    fireEvent.click(within(panel).getByRole("button", { name: "Show 1 handled" }));
    const [denied] = within(within(panel).getByRole("list", { name: "Handled" })).getAllByRole(
      "listitem",
    );
    if (!denied) throw new Error("one handled problem expected");
    for (const text of [
      "Guard blocked",
      "git push origin main",
      "rule no-push-main",
      "Subagent · Explore",
    ]) {
      expect(within(denied).getByText(text)).toBeInTheDocument();
    }
    expect(within(denied).queryByText("Handled by the agent")).not.toBeInTheDocument();
  });

  it("folds into one line saying nothing needs the owner when the agent dealt with every problem (AC-265.6)", () => {
    render(
      <ProblemsPanel
        problems={aSessionProblems({
          summary: [{ event_id: DENIED, text: "The guard blocked git push; the agent continued" }],
          items: [
            aSessionProblem({ event_id: FAILED, resolution: "recovered" }),
            aSessionProblem({
              event_id: DENIED,
              kind: "guard_denied",
              resolution: "agent_continued",
            }),
          ],
        })}
        timeOf={(at) => at.slice(11, 19)}
        onOpen={vi.fn()}
      />,
    );

    const panel = screen.getByRole("region", { name: "What went wrong" });
    expect(
      within(panel).getByText(
        "Nothing needs you · the agent dealt with 2 problems: 1 command failed · 1 guard blocked",
      ),
    ).toBeInTheDocument();
    expect(within(panel).queryByRole("list")).not.toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: "Show 2 handled" }));
    expect(within(panel).getByRole("list", { name: "Summary" })).toBeInTheDocument();
    expect(
      within(within(panel).getByRole("list", { name: "Handled" })).getAllByRole("listitem"),
    ).toHaveLength(2);
  });

  it("opens the moment of a problem or of a summary line when its link is pressed", () => {
    const onOpen = vi.fn();
    renderPanel(onOpen);
    fireEvent.click(screen.getByRole("button", { name: "Show 1 handled" }));

    fireEvent.click(screen.getByRole("link", { name: "Open moment: Guard blocked at 14:08:00" }));
    expect(onOpen).toHaveBeenCalledWith(DENIED);
    fireEvent.click(screen.getAllByRole("link", { name: /^Open moment$/ })[0] ?? document.body);
    expect(onOpen).toHaveBeenLastCalledWith(FAILED);
  });

  it("says who must act for every resolution", () => {
    render(
      <>
        <ProblemBadge problem={aSessionProblem({ resolution: "needs_you" })} />
        <ProblemBadge problem={aSessionProblem({ resolution: "open" })} />
        <ProblemBadge problem={aSessionProblem({ resolution: "recovered" })} />
        <ProblemBadge problem={aSessionProblem({ resolution: "by_you", kind: "interrupted" })} />
        <ProblemBadge
          problem={aSessionProblem({ resolution: "by_you", kind: "guard_ask_declined" })}
        />
        <ProblemBadge problem={aSessionProblem({ resolution: "by_you", kind: "gate_failed" })} />
      </>,
    );

    for (const label of [
      "Needs you",
      "Agent is on it",
      "Handled by the agent",
      "You interrupted",
      "You declined",
      "Handled by you",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("counts problems by who must act", () => {
    expect(
      problemCounts([
        aSessionProblem({ resolution: "needs_you" }),
        aSessionProblem({ resolution: "open" }),
        aSessionProblem({ resolution: "recovered" }),
        aSessionProblem({ resolution: "by_you" }),
      ]),
    ).toBe("1 needs you · 1 agent is on it · 1 handled by the agent · 1 by you");
  });

  it("counts the kinds of problems, most frequent first (AC-265.6)", () => {
    expect(
      kindCounts([
        aSessionProblem({ kind: "guard_denied" }),
        aSessionProblem({ kind: "command_exit" }),
        aSessionProblem({ kind: "command_exit" }),
      ]),
    ).toBe("2 command failed · 1 guard blocked");
  });

  it("renders nothing when the session has no problem", () => {
    const { container } = render(
      <ProblemsPanel
        problems={aSessionProblems({ items: [], summary: [] })}
        timeOf={() => ""}
        onOpen={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = renderPanel();
    expect(await seriousViolations(container)).toEqual([]);
  });
});
