import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiProblem } from "../../lib/api";
import { aPermissionRequest, anAgentSession } from "../../testing/builders";
import { seriousViolations } from "../../testing/axe";
import { PermissionCard, type PermissionAnswer } from "./PermissionCard";
import { applySnapshot, initialTranscript, type PermissionView } from "./transcript";

/** The view of an open request as the reducer builds it from `GET /{id}` (raw, memory). */
function aView(overrides: Parameters<typeof aPermissionRequest>[0] = {}): PermissionView {
  const open = aPermissionRequest(overrides);
  const state = applySnapshot(initialTranscript(), anAgentSession({ open_permission: open }));
  const view = state.permissions[open.request_id];
  if (!view) throw new Error("no view");
  return view;
}

function open(
  request: PermissionView,
  onAnswer = vi.fn<(answer: PermissionAnswer) => Promise<void>>(() => Promise.resolve()),
) {
  const view = render(<PermissionCard request={request} onAnswer={onAnswer} />);
  return { ...view, onAnswer, card: screen.getByRole("region") };
}

describe("PermissionCard (permission)", () => {
  it("shows tool, summary and only localSettings suggestions and takes focus when it arrives", () => {
    const { card } = open(aView());

    expect(card).toHaveAccessibleName("Claude wants to use Bash");
    expect(card).toHaveFocus();
    expect(within(card).getByLabelText("What it will run")).toHaveTextContent("git status");
    expect(within(card).getByRole("button", { name: "Allow once" })).toBeEnabled();
    expect(
      within(card).getByRole("button", { name: "Always allow Bash(git status)" }),
    ).toBeEnabled();
    expect(within(card).queryByRole("button", { name: /setMode/ })).toBeNull();
    expect(within(card).getByRole("button", { name: "Deny" })).toBeEnabled();
  });

  it("posts once and disables the card when answered", async () => {
    const { card, onAnswer } = open(aView());
    const allow = within(card).getByRole("button", { name: "Allow once" });

    await userEvent.click(allow);
    await userEvent.click(allow);

    expect(onAnswer).toHaveBeenCalledTimes(1);
    expect(onAnswer).toHaveBeenCalledWith({ decision: "allow" });
    expect(allow).toBeDisabled();
    expect(within(card).getByRole("button", { name: "Deny" })).toBeDisabled();
    expect(within(card).getByRole("status")).toHaveTextContent("Sending your answer…");
  });

  it("sends the suggestion index when always allow is chosen", async () => {
    const { card, onAnswer } = open(aView());

    await userEvent.click(within(card).getByRole("button", { name: /Always allow/ }));

    expect(onAnswer).toHaveBeenCalledWith({ decision: "always", suggestion: 0 });
  });

  it("sends the message when denied with one", async () => {
    const { card, onAnswer } = open(aView());

    await userEvent.type(within(card).getByLabelText(/Message to Claude/), "Not on main");
    await userEvent.click(within(card).getByRole("button", { name: "Deny" }));

    expect(onAnswer).toHaveBeenCalledWith({ decision: "deny", message: "Not on main" });
  });

  it("denies with the message when Enter is pressed in it", async () => {
    const { card, onAnswer } = open(aView());

    await userEvent.type(within(card).getByLabelText(/Message to Claude/), "No{Enter}");

    expect(onAnswer).toHaveBeenCalledWith({ decision: "deny", message: "No" });
  });

  it("enables the card again with the problem when the post fails", async () => {
    const onAnswer = vi.fn(() =>
      Promise.reject(new ApiProblem({ status: 409, title: "Already answered" })),
    );
    const { card } = open(aView(), onAnswer);

    await userEvent.click(within(card).getByRole("button", { name: "Allow once" }));

    expect(await within(card).findByRole("alert")).toHaveTextContent("Already answered");
    expect(within(card).getByRole("button", { name: "Allow once" })).toBeEnabled();
  });

  it("shows how it ended and no actions when the request is decided", () => {
    const decided: PermissionView = {
      ...aView(),
      decision: { decision: "deny", by: "timeout", message: null, at: "2026-10-11T14:10:00Z" },
    };
    render(<PermissionCard request={decided} onAnswer={vi.fn()} />);

    expect(screen.getByRole("status")).toHaveTextContent("Denied: no answer before the deadline");
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByRole("region")).not.toHaveFocus();
  });

  it.each([
    [{ decision: "allow", by: "web", message: null }, "Allowed once"],
    [{ decision: "always", by: "web", message: null }, "Always allowed"],
    [{ decision: "deny", by: "closed", message: null }, "Denied: the session closed"],
    [{ decision: "deny", by: "web", message: "Use a branch" }, "Denied: Use a branch"],
    [{ decision: "deny", by: "web", message: null }, "Denied"],
  ] as const)("reads %j as %s", (decision, text) => {
    render(
      <PermissionCard
        request={{ ...aView(), decision: { ...decision, at: "2026-10-11T14:10:00Z" } }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(new RegExp(`^${text}$`));
  });

  it("answers an AskUserQuestion with an option and with Other text", async () => {
    const request = aView({
      request_kind: "ask_user_question",
      tool: "AskUserQuestion",
      summary: "Two questions",
      suggestions: [],
      input: {
        questions: [
          {
            question: "Which database?",
            header: "DB",
            multiSelect: false,
            options: [
              { label: "SQLite", description: "Local file" },
              { label: "Postgres", description: "Server" },
            ],
          },
          {
            question: "Which checks?",
            multiSelect: true,
            options: [{ label: "lint" }, { label: "types" }],
          },
        ],
      },
    });
    const { card, onAnswer } = open(request);
    const send = within(card).getByRole("button", { name: "Send answers" });
    expect(card).toHaveAccessibleName("Claude has a question");
    expect(send).toBeDisabled();

    const db = within(card).getByRole("group", { name: "DB Which database?" });
    await userEvent.click(within(db).getByRole("button", { name: "SQLite" }));
    expect(within(db).getByRole("button", { name: "SQLite" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const checks = within(card).getByRole("group", { name: "Which checks?" });
    await userEvent.click(within(checks).getByRole("button", { name: "lint" }));
    await userEvent.click(within(checks).getByRole("button", { name: "types" }));
    await userEvent.click(within(checks).getByRole("button", { name: "lint" }));
    await userEvent.click(within(db).getByRole("button", { name: "Other" }));
    await userEvent.type(within(db).getByLabelText("Your answer"), "DuckDB");
    await userEvent.click(send);

    expect(onAnswer).toHaveBeenCalledWith({
      decision: "allow",
      answers: { "Which database?": "DuckDB", "Which checks?": "types" },
    });
  });

  it("approves a plan with the mode to continue in, or keeps planning", async () => {
    const request = aView({
      request_kind: "plan_approval",
      tool: "ExitPlanMode",
      summary: "Plan",
      suggestions: [],
      input: { plan: "## Plan\n\n1. Write the **test**" },
    });
    const { card, onAnswer } = open(request);
    expect(card).toHaveAccessibleName("Claude finished a plan");
    expect(within(card).getByRole("heading", { name: "Plan" })).toBeInTheDocument();
    expect(within(card).getByText("test").tagName).toBe("STRONG");

    await userEvent.selectOptions(within(card).getByLabelText("Then continue in"), "acceptEdits");
    await userEvent.click(within(card).getByRole("button", { name: "Approve plan" }));

    expect(onAnswer).toHaveBeenCalledWith({ decision: "allow", mode: "acceptEdits" });
  });

  it("lets the plan be refused with a reason", async () => {
    const { card, onAnswer } = open(
      aView({
        request_kind: "plan_approval",
        tool: "ExitPlanMode",
        suggestions: [],
        input: { plan: "1. Do it" },
      }),
    );

    await userEvent.click(within(card).getByRole("button", { name: "Keep planning" }));

    expect(onAnswer).toHaveBeenCalledWith({ decision: "deny" });
  });

  it("names the automatic deny and has no serious violation (a11y)", async () => {
    const { container } = open(aView());

    expect(screen.getByText(/Denied automatically at/)).toBeInTheDocument();
    expect(await seriousViolations(container)).toEqual([]);
  });
});
