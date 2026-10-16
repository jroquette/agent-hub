import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiProblem } from "../../lib/api";
import { servedCheckout } from "../../lib/devCheckout";
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

vi.mock("../../lib/devCheckout", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/devCheckout")>();
  return { ...actual, servedCheckout: vi.fn(() => null) };
});

describe("NewSessionDialog (new-session)", () => {
  it("offers Auto too, with its hint, in the dev app of make playground", async () => {
    vi.mocked(servedCheckout).mockReturnValue("/srv/demo/agent-hub");
    const { dialog } = open();
    const modes = within(dialog).getByRole("group", { name: "Mode" });

    expect(
      within(modes)
        .getAllByRole("radio")
        .map((r) => r.getAttribute("value")),
    ).toEqual(["default", "acceptEdits", "plan", "auto"]);
    await userEvent.click(within(modes).getByRole("radio", { name: /Auto/ }));
    expect(dialog).toHaveTextContent("a safety check blocks risky actions");
    vi.mocked(servedCheckout).mockReturnValue(null);
  });

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

const SHOT = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==";

describe("NewSessionDialog (shake to start a session)", () => {
  it("shake-opens: prompt focused, checkbox checked, thumbnail with alt", async () => {
    const { dialog, props } = open({ screenshot: { dataUrl: SHOT } });

    const prompt = within(dialog).getByRole("textbox", { name: "First prompt (optional)" });
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
    expect(within(dialog).getByRole("textbox", { name: "First prompt (optional)" })).toHaveFocus();

    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));
    expect(vi.mocked(props.onSubmit).mock.calls[0]?.[0]).not.toHaveProperty("screenshot");
  });

  it("new-session-button: no checkbox, body identical to today", async () => {
    const { dialog, props } = open();

    expect(within(dialog).queryByRole("checkbox")).toBeNull();
    expect(within(dialog).queryByRole("img")).toBeNull();
    expect(within(dialog).getByRole("combobox", { name: "Working folder" })).toHaveFocus();
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
    const prompt = within(dialog).getByRole("textbox", { name: "First prompt (optional)" });

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

  it("live-edit: initial workdir and acceptEdits", () => {
    const { dialog } = open({
      screenshot: { dataUrl: SHOT },
      initialWorkdirId: WORKTREE.workdir_id,
      initialMode: "acceptEdits",
    });

    expect(within(dialog).getByRole("combobox", { name: "Working folder" })).toHaveValue(
      WORKTREE.workdir_id,
    );
    expect(within(dialog).getByRole("radio", { name: /Accept edits/ })).toBeChecked();
    expect(within(dialog).queryByRole("note")).toBeNull();
  });

  it("live-edit-fallback: the note shows and the defaults are kept", () => {
    const { dialog } = open({
      screenshot: { dataUrl: SHOT },
      initialWorkdirId: "ffffffffffffffff",
      note: "Live reload needs make dev in a listed folder",
    });

    expect(within(dialog).getByRole("combobox", { name: "Working folder" })).toHaveValue(
      aWorkdir().workdir_id,
    );
    expect(within(dialog).getByRole("radio", { name: /Ask/ })).toBeChecked();
    expect(within(dialog).getByRole("note")).toHaveTextContent(
      "Live reload needs make dev in a listed folder",
    );
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
