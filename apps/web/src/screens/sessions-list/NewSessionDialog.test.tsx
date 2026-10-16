import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiProblem } from "../../lib/api";
import { seriousViolations } from "../../testing/axe";
import { aCapabilities, anAgentSession, aWorkdir } from "../../testing/builders";
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
  const view = render(<NewSessionDialog {...props} />);
  const name = props.resume ? "Resume session" : "New session";
  return { props, view, dialog: screen.getByRole("dialog", { name }) };
}

/** Opens the collapsed "Options" disclosure (Mode, Model). */
async function options(dialog: HTMLElement) {
  await userEvent.click(within(dialog).getByRole("button", { name: "Options" }));
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("NewSessionDialog (new-session)", () => {
  it("offers only the listed workdirs, the three modes and the capabilities' models", async () => {
    const { dialog } = open();
    await options(dialog);

    const folder = within(dialog).getByRole("combobox", { name: "Working folder" });
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
    await options(dialog);
    await userEvent.click(within(dialog).getByRole("radio", { name: /Plan/ }));
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "Model" }), "opus");
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "Prompt" }),
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
    const prompt = within(dialog).getByRole("textbox", { name: "Prompt" });

    await userEvent.type(prompt, "the login bug");
    const skills = within(dialog).getByRole("group", { name: "Skills" });
    await userEvent.click(within(skills).getByRole("button", { name: "/fix" }));
    expect(prompt).toHaveValue("/fix the login bug");
    await userEvent.click(within(skills).getByRole("button", { name: "/review" }));

    expect(prompt).toHaveValue("/review the login bug");
  });

  it("checks a free model id against the pattern before submitting", async () => {
    const { dialog, props } = open();
    await options(dialog);

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

  it("refuses a first prompt over the byte limit", async () => {
    const { dialog } = open({ maxPromptBytes: 1024 });

    await userEvent.click(within(dialog).getByRole("textbox", { name: "Prompt" }));
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

    within(dialog).getByRole("button", { name: "Close" }).focus();
    await userEvent.tab({ shift: true });
    expect(within(dialog).getByRole("button", { name: "Start session" })).toHaveFocus();
    await userEvent.tab();
    expect(within(dialog).getByRole("button", { name: "Close" })).toHaveFocus();
    expect(await seriousViolations(dialog)).toEqual([]);
  });
});

const SHOT = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==";

describe("NewSessionDialog (shake to start a session)", () => {
  it("shake-opens: prompt focused, checkbox checked, thumbnail with alt", async () => {
    const { dialog, props } = open({ screenshot: { dataUrl: SHOT } });

    const prompt = within(dialog).getByRole("textbox", { name: "Prompt" });
    expect(prompt).toHaveFocus();
    const attach = within(dialog).getByRole("checkbox", {
      name: "Attach a screenshot of the current screen",
    });
    expect(attach).toBeChecked();
    expect(attach).toBeEnabled();
    expect(
      within(dialog).getByRole("img", { name: "Screenshot of the screen you shook" }),
    ).toHaveAttribute("src", SHOT);

    await userEvent.type(prompt, "What is on this screen?");
    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));

    expect(props.onSubmit).toHaveBeenCalledWith({
      project: "agent-hub",
      workdir_id: aWorkdir().workdir_id,
      mode: "default",
      model: "default",
      prompt: "What is on this screen?",
      resume_session_id: null,
      fork: false,
      screenshot: { media_type: "image/png", data: "iVBORw0KGgoAAAANSUhEUg==" },
    });
    expect(await seriousViolations(dialog)).toEqual([]);
  });

  it("screenshot-unchecked: body has no screenshot key", async () => {
    const { dialog, props } = open({ screenshot: { dataUrl: SHOT } });

    await userEvent.click(
      within(dialog).getByRole("checkbox", { name: "Attach a screenshot of the current screen" }),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));

    expect(props.onSubmit).toHaveBeenCalledTimes(1);
    const body = vi.mocked(props.onSubmit).mock.calls[0]?.[0];
    expect(body).not.toHaveProperty("screenshot");
    expect(body).toMatchObject({ prompt: null });
  });

  it("capture-failed: checkbox unchecked and disabled, note, no thumbnail, no screenshot", async () => {
    const { dialog, props } = open({ screenshot: { failed: true } });

    const attach = within(dialog).getByRole("checkbox", {
      name: "Attach a screenshot of the current screen",
    });
    expect(attach).not.toBeChecked();
    expect(attach).toBeDisabled();
    expect(within(dialog).getByText("No screenshot was taken")).toBeInTheDocument();
    expect(within(dialog).queryByRole("img")).toBeNull();
    expect(within(dialog).getByRole("textbox", { name: "Prompt" })).toHaveFocus();

    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));
    expect(vi.mocked(props.onSubmit).mock.calls[0]?.[0]).not.toHaveProperty("screenshot");
  });

  it("new-session-button: no checkbox, body identical to today", async () => {
    const { dialog, props } = open();

    expect(within(dialog).queryByRole("checkbox")).toBeNull();
    expect(within(dialog).queryByRole("img")).toBeNull();
    expect(within(dialog).getByRole("textbox", { name: "Prompt" })).toHaveFocus();
    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));

    expect(props.onSubmit).toHaveBeenCalledWith({
      project: "agent-hub",
      workdir_id: aWorkdir().workdir_id,
      mode: "default",
      model: "default",
      prompt: null,
      resume_session_id: null,
      fork: false,
    });
    expect(Object.keys(vi.mocked(props.onSubmit).mock.calls[0]?.[0] ?? {})).toEqual([
      "project",
      "workdir_id",
      "mode",
      "model",
      "prompt",
      "resume_session_id",
      "fork",
    ]);
  });

  it("needs a prompt while the screenshot is attached", async () => {
    const { dialog } = open({ screenshot: { dataUrl: SHOT } });
    const start = within(dialog).getByRole("button", { name: "Start session" });
    const prompt = within(dialog).getByRole("textbox", { name: "Prompt" });

    expect(start).toBeDisabled();
    expect(
      within(dialog).getByText("The screenshot goes with the first prompt: write one."),
    ).toBeInTheDocument();
    await userEvent.type(prompt, "   ");
    expect(start).toBeDisabled();
    await userEvent.type(prompt, "Why?");
    expect(start).toBeEnabled();
    await userEvent.clear(prompt);
    await userEvent.click(
      within(dialog).getByRole("checkbox", { name: "Attach a screenshot of the current screen" }),
    );
    expect(start).toBeEnabled();
  });

  it("live-edit: initial workdir and acceptEdits", async () => {
    window.localStorage.setItem("ah.sessions.workdir.agent-hub", aWorkdir().workdir_id);
    const { dialog } = open({
      screenshot: { dataUrl: SHOT },
      initialWorkdirId: WORKTREE.workdir_id,
      initialMode: "acceptEdits",
    });

    expect(within(dialog).getByRole("combobox", { name: "Working folder" })).toHaveValue(
      WORKTREE.workdir_id,
    );
    await options(dialog);
    expect(within(dialog).getByRole("radio", { name: /Accept edits/ })).toBeChecked();
    expect(within(dialog).queryByRole("note")).toBeNull();
  });

  it("live-edit-fallback: the note shows and the defaults are kept", async () => {
    const { dialog } = open({
      screenshot: { dataUrl: SHOT },
      initialWorkdirId: "ffffffffffffffff",
      note: "Live reload needs make dev in a listed folder",
    });

    expect(within(dialog).getByRole("combobox", { name: "Working folder" })).toHaveValue(
      aWorkdir().workdir_id,
    );
    await options(dialog);
    expect(within(dialog).getByRole("radio", { name: /Ask/ })).toBeChecked();
    expect(within(dialog).getByRole("note")).toHaveTextContent(
      "Live reload needs make dev in a listed folder",
    );
  });
});

describe("NewSessionDialog (new-session-dialog)", () => {
  const STORED = "ah.sessions.workdir.agent-hub";

  it("shows only Where and the focused Prompt; Mode and Model wait in Options", async () => {
    const { dialog } = open({ projects: ["agent-hub", "ops"] });

    const where = within(dialog).getByRole("group", { name: "Where" });
    expect(within(where).getByRole("combobox", { name: "Project" })).toHaveValue("agent-hub");
    expect(within(where).getByRole("combobox", { name: "Working folder" })).toHaveValue(
      aWorkdir().workdir_id,
    );
    expect(within(dialog).getByRole("textbox", { name: "Prompt" })).toHaveFocus();
    expect(within(dialog).queryByRole("group", { name: "Mode" })).toBeNull();
    expect(within(dialog).queryByRole("combobox", { name: "Model" })).toBeNull();
    expect(within(dialog).queryByRole("combobox", { name: "Start from" })).toBeNull();
    expect(within(dialog).queryByRole("checkbox", { name: /Fork/ })).toBeNull();
    const toggle = within(dialog).getByRole("button", { name: "Options" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAccessibleDescription("Ask before edits · default");

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(within(dialog).getByRole("radio", { name: /Plan/ }));
    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "Model" }), "opus");
    expect(toggle).toHaveAccessibleDescription("Plan · opus");
    await userEvent.click(toggle);
    expect(within(dialog).queryByRole("group", { name: "Mode" })).toBeNull();
    expect(await seriousViolations(dialog)).toEqual([]);
  });

  it("names the project as text when there is no other to choose", () => {
    const { dialog } = open({ projects: ["agent-hub"] });

    const where = within(dialog).getByRole("group", { name: "Where" });
    expect(within(where).queryByRole("combobox", { name: "Project" })).toBeNull();
    expect(where).toHaveTextContent("agent-hub");
  });

  it("asks for the chosen project's folders and keeps the prompt", async () => {
    const onProjectChange = vi.fn();
    const { dialog, props, view } = open({ projects: ["agent-hub", "ops"], onProjectChange });
    const prompt = within(dialog).getByRole("textbox", { name: "Prompt" });
    await userEvent.type(prompt, "Check ops");

    await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "Project" }), "ops");
    expect(onProjectChange).toHaveBeenCalledWith("ops");
    view.rerender(<NewSessionDialog {...props} project="ops" workdirs={undefined} />);
    expect(within(dialog).getByText("Loading the working folders…")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Start session" })).toBeDisabled();

    const ops = aWorkdir({ label: "ops-hub", workdir_id: "00000000000000aa" });
    view.rerender(<NewSessionDialog {...props} project="ops" workdirs={[ops]} />);
    expect(within(dialog).getByRole("combobox", { name: "Working folder" })).toHaveValue(
      ops.workdir_id,
    );
    expect(prompt).toHaveValue("Check ops");
  });

  it("preselects the folder last used for the project and remembers the one started in", async () => {
    window.localStorage.setItem(STORED, WORKTREE.workdir_id);
    const { dialog, props } = open();

    const folder = within(dialog).getByRole("combobox", { name: "Working folder" });
    expect(folder).toHaveValue(WORKTREE.workdir_id);
    await userEvent.selectOptions(folder, aWorkdir().workdir_id);
    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));

    expect(props.onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ workdir_id: aWorkdir().workdir_id }),
    );
    expect(window.localStorage.getItem(STORED)).toBe(aWorkdir().workdir_id);
    expect(window.localStorage.getItem("ah.sessions.workdir.ops")).toBeNull();
  });

  it("keeps the stored folder when the choice changes and the dialog is cancelled", async () => {
    window.localStorage.setItem(STORED, WORKTREE.workdir_id);
    const { dialog, props } = open();

    await userEvent.selectOptions(
      within(dialog).getByRole("combobox", { name: "Working folder" }),
      aWorkdir().workdir_id,
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(props.onCancel).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem(STORED)).toBe(WORKTREE.workdir_id);
  });

  it("starts on Ctrl+Enter and Cmd+Enter, never on a plain Enter in the prompt", async () => {
    const { dialog, props } = open();
    const prompt = within(dialog).getByRole("textbox", { name: "Prompt" });

    await userEvent.type(prompt, "one{Enter}two");
    expect(props.onSubmit).not.toHaveBeenCalled();
    expect(prompt).toHaveValue("one\ntwo");
    await userEvent.keyboard("{Control>}{Enter}{/Control}");
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
    expect(props.onSubmit).toHaveBeenCalledWith(expect.objectContaining({ prompt: "one\ntwo" }));
    await userEvent.keyboard("{Meta>}{Enter}{/Meta}");
    expect(props.onSubmit).toHaveBeenCalledTimes(2);
  });

  it("does not start on Ctrl+Enter while an input method is composing", () => {
    const { dialog, props } = open();

    const prompt = within(dialog).getByRole("textbox", { name: "Prompt" });
    fireEvent.keyDown(prompt, { key: "Enter", ctrlKey: true, isComposing: true });
    expect(props.onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(prompt, { key: "Enter", ctrlKey: true });
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
  });

  it("does not start on Ctrl+Enter while Start is disabled", async () => {
    const { dialog, props } = open({ screenshot: { dataUrl: SHOT } });

    within(dialog).getByRole("textbox", { name: "Prompt" }).focus();
    await userEvent.keyboard("{Control>}{Enter}{/Control}");

    expect(props.onSubmit).not.toHaveBeenCalled();
  });

  it.each([
    [{ screenshot: { dataUrl: SHOT } }, "Write a prompt to send the screenshot."],
    [{ workdirs: [] }, "No working folder to start in."],
    [{ workdirs: undefined }, "Waiting for the working folders."],
    [
      { capabilities: aCapabilities({ available: false }) },
      "Sessions cannot start on this machine.",
    ],
  ] satisfies [Partial<NewSessionDialogProps>, string][])(
    "says inline why Start is disabled (%#)",
    (overrides, reason) => {
      const { dialog } = open(overrides);

      const start = within(dialog).getByRole("button", { name: "Start session" });
      expect(start).toBeDisabled();
      expect(start).toHaveAccessibleDescription(reason);
    },
  );

  it("points to Options when the model id there is not valid, and drops the reason once fixed", async () => {
    const { dialog } = open();
    const start = within(dialog).getByRole("button", { name: "Start session" });
    expect(start).not.toHaveAttribute("aria-describedby");

    await options(dialog);
    await userEvent.selectOptions(
      within(dialog).getByRole("combobox", { name: "Model" }),
      "__other__",
    );
    expect(start).toHaveAccessibleDescription("Options: the model id is not valid.");
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Model id" }), "opus");

    expect(start).toBeEnabled();
    expect(start).not.toHaveAttribute("aria-describedby");
  });
});

describe("NewSessionDialog (workdir-stale)", () => {
  it("falls back to the first folder when the stored one is no longer listed", () => {
    window.localStorage.setItem("ah.sessions.workdir.agent-hub", "ffffffffffffffff");
    const { dialog } = open();

    expect(within(dialog).getByRole("combobox", { name: "Working folder" })).toHaveValue(
      aWorkdir().workdir_id,
    );
  });

  it("falls back to the first folder when storage throws", () => {
    const read = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    try {
      const { dialog } = open();
      expect(within(dialog).getByRole("combobox", { name: "Working folder" })).toHaveValue(
        aWorkdir().workdir_id,
      );
    } finally {
      read.mockRestore();
    }
  });
});

describe("NewSessionDialog (resume)", () => {
  const ENDED = anAgentSession({
    status: "ended",
    end_reason: "closed",
    title: "Fix the flaky test",
    workdir_id: WORKTREE.workdir_id,
    workdir_label: "agh-7-collector",
    mode: "plan",
    model: "opus",
    ended_at: "2026-10-16T09:30:00Z",
  });

  function resume(overrides: Partial<NewSessionDialogProps> = {}) {
    return open({ resume: ENDED, workdirs: undefined, ...overrides });
  }

  it("resume: names the target (title, folder, when it ended) and offers Fork, not the folder picker", () => {
    const { dialog } = resume();

    const target = within(dialog).getByRole("group", { name: "Resume" });
    expect(target).toHaveTextContent("Fix the flaky test");
    expect(target).toHaveTextContent("agent-hub › agh-7-collector");
    expect(within(target).getByText(/Ended/).querySelector("time")).toHaveAttribute(
      "datetime",
      "2026-10-16T09:30:00Z",
    );
    expect(within(dialog).queryByRole("combobox", { name: "Working folder" })).toBeNull();
    expect(within(dialog).getByRole("checkbox", { name: /Fork/ })).not.toBeChecked();
    expect(within(dialog).getByRole("textbox", { name: "Prompt" })).toHaveFocus();
  });

  it("resume: sends the target's folder and Claude session, its mode and model, and the Fork choice", async () => {
    const { dialog, props } = resume();

    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));
    await userEvent.click(within(dialog).getByRole("checkbox", { name: /Fork/ }));
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Prompt" }), "Go on");
    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));

    const sent = {
      project: "agent-hub",
      workdir_id: WORKTREE.workdir_id,
      mode: "plan",
      model: "opus",
      resume_session_id: ENDED.claude_session_id,
    };
    expect(props.onSubmit).toHaveBeenNthCalledWith(1, { ...sent, prompt: null, fork: false });
    expect(props.onSubmit).toHaveBeenNthCalledWith(2, { ...sent, prompt: "Go on", fork: true });
  });

  it("resume: keeps a model id the capabilities do not list", async () => {
    const { dialog, props } = resume({ resume: { ...ENDED, model: "claude-sonnet-4-5" } });

    await options(dialog);
    expect(within(dialog).getByRole("textbox", { name: "Model id" })).toHaveValue(
      "claude-sonnet-4-5",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));
    expect(vi.mocked(props.onSubmit).mock.calls[0]?.[0]).toMatchObject({
      model: "claude-sonnet-4-5",
    });
  });

  it("resume: a plain New session shows no resume target and no Fork", () => {
    const { dialog } = open();

    expect(within(dialog).queryByRole("group", { name: "Resume" })).toBeNull();
    expect(within(dialog).queryByRole("checkbox", { name: /Fork/ })).toBeNull();
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
