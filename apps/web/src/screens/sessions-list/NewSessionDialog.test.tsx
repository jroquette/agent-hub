import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiProblem } from "../../lib/api";
import { seriousViolations } from "../../testing/axe";
import { T0, aCapabilities, aWorkdir } from "../../testing/builders";
import {
  NewSessionDialog,
  withSkill,
  workdirText,
  type NewSessionDialogProps,
} from "./NewSessionDialog";

const WORKTREE = aWorkdir({
  kind: "worktree",
  label: "agh-7-collector",
  repo: "agent-hub",
  skills: ["fix", "review"],
  workdir_id: "0123456789abcdef",
  worktree: "agh-7-collector",
});

function open(overrides: Partial<NewSessionDialogProps> = {}) {
  const props: NewSessionDialogProps = {
    project: "agent-hub",
    workdirs: [aWorkdir(), WORKTREE],
    capabilities: aCapabilities(),
    pending: false,
    error: null,
    onSubmit: vi.fn(),
    onCancel: vi.fn(),
    ...overrides,
  };
  render(<NewSessionDialog {...props} />);
  return { props, dialog: screen.getByRole("dialog", { name: "New session" }) };
}

describe("NewSessionDialog (new-session)", () => {
  it("offers only the listed workdirs, the three modes and the capabilities' models", () => {
    const { dialog } = open();

    const folder = within(dialog).getByRole("combobox", { name: "Working folder" });
    expect(folder).toHaveFocus();
    expect(
      within(folder)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["agent-hub-hub (hub)", "agh-7-collector (worktree of agent-hub)"]);
    expect(within(dialog).queryByRole("textbox", { name: /path/i })).toBeNull();
    expect(
      within(within(dialog).getByRole("group", { name: "Mode" }))
        .getAllByRole("radio")
        .map((r) => r.getAttribute("value")),
    ).toEqual(["default", "acceptEdits", "plan"]);
    expect(dialog).not.toHaveTextContent(/bypass/i);
    const model = within(dialog).getByRole("combobox", { name: "Model" });
    expect(
      within(model)
        .getAllByRole("option")
        .map((o) => o.getAttribute("value")),
    ).toEqual(["default", "opus", "sonnet", "haiku", "__other__"]);
  });

  it("submits the chosen folder, mode, model and first prompt", async () => {
    const { dialog, props } = open();

    await userEvent.selectOptions(
      within(dialog).getByRole("combobox", { name: "Working folder" }),
      "0123456789abcdef",
    );
    await userEvent.click(within(dialog).getByRole("radio", { name: /Plan/ }));
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "Model" }), "opus");
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "First prompt (optional)" }),
      "  Fix the flaky test  ",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));

    expect(props.onSubmit).toHaveBeenCalledWith({
      project: "agent-hub",
      workdir_id: "0123456789abcdef",
      mode: "plan",
      model: "opus",
      prompt: "Fix the flaky test",
      resume_session_id: null,
      fork: false,
    });
  });

  it("puts a /skill in front of the prompt from the folder's skills", async () => {
    const { dialog } = open({ workdirs: [WORKTREE] });
    const prompt = within(dialog).getByRole("textbox", { name: "First prompt (optional)" });

    await userEvent.type(prompt, "the login bug");
    const skills = within(dialog).getByRole("group", { name: "Skills" });
    await userEvent.click(within(skills).getByRole("button", { name: "/fix" }));
    expect(prompt).toHaveValue("/fix the login bug");
    await userEvent.click(within(skills).getByRole("button", { name: "/review" }));

    expect(prompt).toHaveValue("/review the login bug");
  });

  it("checks a free model id against the pattern before submitting", async () => {
    const { dialog, props } = open();

    await userEvent.selectOptions(
      within(dialog).getByRole("combobox", { name: "Model" }),
      "__other__",
    );
    const id = within(dialog).getByRole("textbox", { name: "Model id" });
    await userEvent.type(id, "bad id;rm");
    const start = within(dialog).getByRole("button", { name: "Start session" });
    expect(id).toHaveAttribute("aria-invalid", "true");
    expect(start).toBeDisabled();

    await userEvent.clear(id);
    await userEvent.paste("claude-sonnet-4-5[1m]");
    await userEvent.click(start);

    expect(props.onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ model: "claude-sonnet-4-5[1m]", prompt: null }),
    );
  });

  it("resumes or forks a past session of the folder when one is chosen", async () => {
    const onWorkdirChange = vi.fn();
    const { dialog, props } = open({
      onWorkdirChange,
      resumable: [
        {
          session_id: "5091b986-0000-7000-8000-000000000009",
          title: "Old work",
          cwd: "/x",
          last_activity: T0,
        },
      ],
    });
    expect(onWorkdirChange).toHaveBeenCalledWith(aWorkdir().workdir_id);

    await userEvent.selectOptions(
      within(dialog).getByRole("combobox", { name: "Start from" }),
      "5091b986-0000-7000-8000-000000000009",
    );
    await userEvent.click(within(dialog).getByRole("checkbox", { name: /Fork/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));

    expect(props.onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        resume_session_id: "5091b986-0000-7000-8000-000000000009",
        fork: true,
      }),
    );
  });

  it("refuses a first prompt over the byte limit", async () => {
    const { dialog } = open({ maxPromptBytes: 1024 });

    await userEvent.click(within(dialog).getByRole("textbox", { name: "First prompt (optional)" }));
    await userEvent.paste("x".repeat(1025));

    expect(within(dialog).getByText("Too long: at most 1 KiB.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Start session" })).toBeDisabled();
  });

  it("shows progress, then the problem, and cancels on Escape when idle", async () => {
    const { props } = open({ pending: true });
    expect(screen.getByRole("status")).toHaveTextContent("Starting the session…");
    expect(screen.getByRole("button", { name: "Starting…" })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    expect(props.onCancel).not.toHaveBeenCalled();
  });

  it("names the problem the server answered and cancels on Escape", async () => {
    const { props } = open({
      error: new ApiProblem({ status: 429, title: "Too many sessions", detail: "At most 4 live" }),
    });

    expect(screen.getByRole("alert")).toHaveTextContent("Too many sessions: At most 4 live");
    await userEvent.keyboard("{Escape}");
    expect(props.onCancel).toHaveBeenCalledTimes(1);
  });

  it("says why it cannot start when the machine has no claude", () => {
    open({ capabilities: aCapabilities({ available: false, reason: "no claude on PATH" }) });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Sessions cannot start here: no claude on PATH.",
    );
    expect(screen.getByRole("button", { name: "Start session" })).toBeDisabled();
  });

  it("says so when the project has no folder", () => {
    open({ workdirs: [] });

    expect(screen.getByText("No working folder found for agent-hub.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start session" })).toBeDisabled();
  });

  it("keeps Tab inside the dialog (new-session a11y)", async () => {
    const { dialog } = open();

    await userEvent.tab({ shift: true });
    expect(within(dialog).getByRole("button", { name: "Start session" })).toHaveFocus();
    await userEvent.tab();
    expect(within(dialog).getByRole("combobox", { name: "Working folder" })).toHaveFocus();
    expect(await seriousViolations(dialog)).toEqual([]);
  });
});

describe("new-session helpers", () => {
  it("names folders and replaces a leading /skill (new-session)", () => {
    expect(workdirText(aWorkdir({ kind: "repo", label: "agent-hub" }))).toBe("agent-hub (repo)");
    expect(workdirText(aWorkdir({ kind: "worktree", label: "w", repo: null }))).toBe(
      "w (worktree)",
    );
    expect(withSkill("", "fix")).toBe("/fix ");
    expect(withSkill("/feature do it", "fix")).toBe("/fix do it");
  });
});
