import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiProblem } from "../../lib/api";
import { seriousViolations } from "../../testing/axe";
import { DecideDialog, MAX_REASON_CHARS, type DecideDialogProps } from "./DecideDialog";

const CONFIRM_TEXT =
  "This opens a pull request in agent-hub-hub. Nothing changes in the brain until you merge it.";

function open(overrides: Partial<DecideDialogProps> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const props: DecideDialogProps = {
    action: "accept",
    title: "Run the web gates with npm ci first",
    hubRepo: "agent-hub-hub",
    notePath: "brain/_inbox/web-gates.md",
    target: "learnings/",
    pending: false,
    error: null,
    onConfirm,
    onCancel,
    ...overrides,
  };
  const result = render(<DecideDialog {...props} />);
  return { ...result, onConfirm, onCancel };
}

describe("DecideDialog", () => {
  it("states that accepting opens a pull request in the hub and where the note goes", async () => {
    const { onConfirm } = open();

    const dialog = screen.getByRole("dialog", { name: "Accept this learning?" });
    expect(dialog).toHaveAccessibleDescription(CONFIRM_TEXT);
    expect(within(dialog).getByText("brain/_inbox/web-gates.md")).toBeInTheDocument();
    expect(within(dialog).getByText("brain/learnings/")).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Open pull request" }));

    expect(onConfirm).toHaveBeenCalledWith("");
  });

  it("names the hub generically when its repo is not known yet", () => {
    open({ hubRepo: null });

    expect(screen.getByRole("dialog")).toHaveAccessibleDescription(
      "This opens a pull request in the hub's repository. Nothing changes in the brain until you merge it.",
    );
  });

  it("asks for a reason before rejecting, up to 300 characters", async () => {
    const { onConfirm } = open({ action: "reject" });

    const dialog = screen.getByRole("dialog", { name: "Reject this learning?" });
    expect(dialog).toHaveAccessibleDescription(CONFIRM_TEXT);
    const confirm = within(dialog).getByRole("button", { name: "Open pull request" });
    expect(confirm).toBeDisabled();
    const reason = within(dialog).getByRole("textbox", { name: /Reason/ });
    expect(reason).toHaveFocus();
    expect(reason).toHaveAttribute("maxLength", String(MAX_REASON_CHARS));
    expect(MAX_REASON_CHARS).toBe(300);

    await userEvent.type(reason, "   ");
    expect(confirm).toBeDisabled();
    await userEvent.type(reason, "Already in the repo docs");
    expect(within(dialog).getByText("27 / 300")).toBeInTheDocument();
    await userEvent.click(confirm);

    expect(onConfirm).toHaveBeenCalledWith("Already in the repo docs");
  });

  it("shows progress and blocks a second submit or cancel while the request runs", async () => {
    const { onCancel } = open({ pending: true });

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Opening pull request…" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(within(dialog).getByRole("status")).toHaveTextContent(
      "Opening the pull request in agent-hub-hub",
    );
    await userEvent.keyboard("{Escape}");
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("closes on Cancel and on Escape", async () => {
    const { onCancel } = open();

    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onCancel).toHaveBeenCalledTimes(2);
  });

  it("keeps the focus inside the dialog", async () => {
    open();

    const confirm = screen.getByRole("button", { name: "Open pull request" });
    expect(confirm).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.tab();
    expect(confirm).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  describe("errors", () => {
    it("shows a conflict's reason", () => {
      open({
        error: new ApiProblem({
          status: 409,
          title: "Conflict",
          detail: "Target already exists in the brain",
        }),
      });

      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent("Could not open the pull request");
      expect(alert).toHaveTextContent("Target already exists in the brain");
    });

    it("says a failed pull request can be retried (502)", () => {
      open({
        error: new ApiProblem({ status: 502, title: "Could not open the pull request" }),
      });

      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent("Could not open the pull request");
      expect(alert).toHaveTextContent("Nothing was changed. Try again.");
    });

    it("says to check the hub's pull requests after a timeout (504)", () => {
      open({
        error: new ApiProblem({ status: 504, title: "Gateway timeout", detail: "Took over 60 s" }),
      });

      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent("Took over 60 s");
      expect(alert).toHaveTextContent(
        "Check the pull requests of agent-hub-hub before trying again.",
      );
    });

    it("says the API could not be reached", () => {
      open({
        error: new ApiProblem({ status: 0, title: "Could not reach agent-hub", detail: "Down." }),
      });

      expect(screen.getByRole("alert")).toHaveTextContent("Could not reach agent-hub");
    });
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = open({
      action: "reject",
      error: new ApiProblem({ status: 409, title: "Conflict", detail: "Already decided" }),
    });

    expect(await seriousViolations(container)).toEqual([]);
  });

  it("has no serious a11y violations while pending (a11y)", async () => {
    const { container } = open({ pending: true });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
