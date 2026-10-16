import "../agent-session/agent-session.css";

import { useEffect, useId, useRef, useState } from "react";

import type { components } from "../../api/schema";
import { Button, Time } from "../../components";
import type { ApiProblem } from "../../lib/api";
import { offeredModes, DEFAULT_MESSAGE_MAX_BYTES } from "../agent-session/Composer";
import { modeLabel, type PermissionMode } from "../agent-session/model";

type Schemas = components["schemas"];
export type Workdir = Schemas["Workdir"];
export type DriverCapabilities = Schemas["DriverCapabilities"];
export type PastSession = Schemas["PastSession"];
export type CreateAgentSession = Schemas["CreateAgentSession"];

/** The screen a shake captured (AGH-260), or the capture that failed. */
export type ShakeScreenshot = { dataUrl: string } | { failed: true };

/** A model id the CLI may take besides the aliases (L6); the server checks the same pattern. */
export const MODEL_PATTERN = /^[A-Za-z0-9._\-[\]]{1,64}$/;
const OTHER_MODEL = "__other__";

const MODE_HINT: Record<PermissionMode, string> = {
  default: "Claude asks before each edit or command.",
  acceptEdits: "File edits run without asking; commands still ask.",
  plan: "Claude plans first and asks you to approve the plan.",
  auto: "Claude works on its own; a safety check blocks risky actions.",
};

/** How a workdir reads in the picker: its label and what it is. */
export function workdirText(workdir: Workdir): string {
  if (workdir.kind === "worktree")
    return `${workdir.label} (worktree${workdir.repo ? ` of ${workdir.repo}` : ""})`;
  return `${workdir.label} (${workdir.kind})`;
}

/** The prompt with `/name ` in front, replacing a `/skill` already there. */
export function withSkill(prompt: string, skill: string): string {
  return `/${skill} ${prompt.replace(/^\/[^\s]+\s*/, "")}`;
}

export interface NewSessionDialogProps {
  project: string;
  /** The folders a session may start in; never a free path (D6). */
  workdirs: readonly Workdir[];
  capabilities: DriverCapabilities;
  /** Past Claude sessions of the chosen folder, once loaded (resume, fork). */
  resumable?: readonly PastSession[] | undefined;
  /** Called with the chosen folder (on open and on change), to load its resumable sessions. */
  onWorkdirChange?: ((workdirId: string) => void) | undefined;
  pending: boolean;
  error: ApiProblem | null;
  maxPromptBytes?: number | undefined;
  /** The body of `POST /agent-sessions`; the caller navigates to the chat view on success. */
  onSubmit: (body: CreateAgentSession) => void;
  onCancel: () => void;
  /** Set when a shake opened the dialog: offers to attach the captured screen (AGH-260). */
  screenshot?: ShakeScreenshot | undefined;
  /** The folder to preselect when it is listed (the checkout `make dev` serves, O8). */
  initialWorkdirId?: string | undefined;
  initialMode?: PermissionMode | undefined;
  /** A short note under the title, such as why live reload is not set up. */
  note?: string | undefined;
}

const FOCUSABLE =
  "button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), a[href]";

/**
 * "New session" (D10, AC-165.42): one of the listed folders, a mode (never bypass), a model alias
 * or id, an optional first prompt with the folder's `/skill` shortcuts, and optionally a past
 * session to resume or fork.
 */
export function NewSessionDialog({
  project,
  workdirs,
  capabilities,
  resumable,
  onWorkdirChange,
  pending,
  error,
  maxPromptBytes = DEFAULT_MESSAGE_MAX_BYTES,
  onSubmit,
  onCancel,
  screenshot,
  initialWorkdirId,
  initialMode,
  note,
}: NewSessionDialogProps) {
  const [workdirId, setWorkdirId] = useState(
    (workdirs.some((w) => w.workdir_id === initialWorkdirId) ? initialWorkdirId : undefined) ??
      workdirs[0]?.workdir_id ??
      "",
  );
  const [mode, setMode] = useState<PermissionMode>(initialMode ?? "default");
  const shot = screenshot && "dataUrl" in screenshot ? screenshot.dataUrl : null;
  const [attach, setAttach] = useState(shot !== null);
  const [model, setModel] = useState(capabilities.models[0] ?? "default");
  const [otherModel, setOtherModel] = useState("");
  const [prompt, setPrompt] = useState("");
  const [resume, setResume] = useState("");
  const [fork, setFork] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const workdirField = useId();
  const modelField = useId();
  const otherField = useId();
  const otherHint = useId();
  const promptField = useId();
  const promptHint = useId();
  const resumeField = useId();
  const forkField = useId();
  const attachField = useId();

  const workdir = workdirs.find((w) => w.workdir_id === workdirId);

  useEffect(() => {
    const before = document.activeElement;
    const first = screenshot
      ? dialog.current?.querySelector<HTMLElement>("textarea")
      : dialog.current?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    return () => {
      if (before instanceof HTMLElement) before.focus();
    };
    // Focus moves once, when the dialog opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (workdirId) onWorkdirChange?.(workdirId);
  }, [workdirId, onWorkdirChange]);

  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        if (!pending) onCancel();
        return;
      }
      if (event.key !== "Tab") return;
      const items = [...node.querySelectorAll<HTMLElement>(FOCUSABLE)];
      const head = items[0];
      const tail = items[items.length - 1];
      if (!head || !tail) return;
      if (event.shiftKey && document.activeElement === head) {
        event.preventDefault();
        tail.focus();
      } else if (!event.shiftKey && document.activeElement === tail) {
        event.preventDefault();
        head.focus();
      }
    };
    node.addEventListener("keydown", onKeyDown);
    return () => {
      node.removeEventListener("keydown", onKeyDown);
    };
  }, [pending, onCancel]);

  const chosenModel = model === OTHER_MODEL ? otherModel.trim() : model;
  const modelValid = MODEL_PATTERN.test(chosenModel);
  const promptBytes = new TextEncoder().encode(prompt).length;
  const promptTooLong = promptBytes > maxPromptBytes;
  const past = resumable ?? [];
  const attached = attach && shot !== null;
  const needsPrompt = attached && prompt.trim() === "";
  const ready =
    capabilities.available &&
    workdir !== undefined &&
    modelValid &&
    !promptTooLong &&
    !needsPrompt &&
    !pending;

  const submit = () => {
    if (!ready) return;
    const text = prompt.trim();
    const body: CreateAgentSession = {
      project,
      workdir_id: workdir.workdir_id,
      mode,
      model: chosenModel,
      prompt: text ? text : null,
      resume_session_id: resume || null,
      fork: resume ? fork : false,
    };
    onSubmit(
      attached
        ? {
            ...body,
            screenshot: { media_type: "image/png", data: shot.slice(shot.indexOf(",") + 1) },
          }
        : body,
    );
  };

  return (
    <div className="ah-scrim">
      <div
        ref={dialog}
        className="ah-dialog as-new-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={pending}
      >
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <div className="ah-dialog-body ah-stack" style={{ gap: 12 }}>
            <h2 id={titleId} className="ah-h3">
              New session
            </h2>
            {note && (
              <p role="note" className="ah-small ah-muted">
                {note}
              </p>
            )}
            {!capabilities.available && (
              <p role="alert" className="as-error">
                Sessions cannot start here: {capabilities.reason ?? "claude is not available"}.
              </p>
            )}

            <div className="ah-stack" style={{ gap: 4 }}>
              <label htmlFor={workdirField} className="ah-small">
                Working folder
              </label>
              {workdirs.length === 0 ? (
                <p className="ah-small ah-muted" id={workdirField}>
                  No working folder found for {project}.
                </p>
              ) : (
                <select
                  id={workdirField}
                  className="ah-input"
                  value={workdirId}
                  disabled={pending}
                  onChange={(event) => {
                    setWorkdirId(event.target.value);
                    setResume("");
                  }}
                >
                  {workdirs.map((w) => (
                    <option key={w.workdir_id} value={w.workdir_id}>
                      {workdirText(w)}
                    </option>
                  ))}
                </select>
              )}
            </div>

            <fieldset className="as-fieldset" disabled={pending}>
              <legend className="ah-small">Mode</legend>
              {offeredModes().map((m) => (
                <label key={m} className="as-radio">
                  <input
                    type="radio"
                    name={`${titleId}-mode`}
                    value={m}
                    checked={mode === m}
                    onChange={() => {
                      setMode(m);
                    }}
                  />
                  {modeLabel(m)}
                  <span className="ah-small ah-muted">{MODE_HINT[m]}</span>
                </label>
              ))}
            </fieldset>

            <div className="ah-stack" style={{ gap: 4 }}>
              <label htmlFor={modelField} className="ah-small">
                Model
              </label>
              <select
                id={modelField}
                className="ah-input"
                value={model}
                disabled={pending}
                onChange={(event) => {
                  setModel(event.target.value);
                }}
              >
                {capabilities.models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
                <option value={OTHER_MODEL}>Other model id…</option>
              </select>
              {model === OTHER_MODEL && (
                <>
                  <label htmlFor={otherField} className="ah-small">
                    Model id
                  </label>
                  <input
                    id={otherField}
                    className="ah-input"
                    value={otherModel}
                    maxLength={64}
                    disabled={pending}
                    aria-invalid={otherModel !== "" && !modelValid}
                    aria-describedby={otherHint}
                    onChange={(event) => {
                      setOtherModel(event.target.value);
                    }}
                  />
                  <span id={otherHint} className="ah-small ah-subtle">
                    {otherModel !== "" && !modelValid
                      ? "Letters, digits and . _ - [ ] only, at most 64."
                      : "For example claude-sonnet-4-5."}
                  </span>
                </>
              )}
            </div>

            {past.length > 0 && (
              <div className="ah-stack" style={{ gap: 4 }}>
                <label htmlFor={resumeField} className="ah-small">
                  Start from
                </label>
                <select
                  id={resumeField}
                  className="ah-input"
                  value={resume}
                  disabled={pending}
                  onChange={(event) => {
                    setResume(event.target.value);
                  }}
                >
                  <option value="">A new conversation</option>
                  {past.map((s) => (
                    <option key={s.session_id} value={s.session_id}>
                      Resume: {s.title ?? s.session_id}
                    </option>
                  ))}
                </select>
                {resume && (
                  <>
                    <label htmlFor={forkField} className="ah-row ah-small" style={{ gap: 6 }}>
                      <input
                        id={forkField}
                        type="checkbox"
                        className="ah-check"
                        checked={fork}
                        disabled={pending}
                        onChange={(event) => {
                          setFork(event.target.checked);
                        }}
                      />
                      Fork: continue in a new session and keep the original unchanged
                    </label>
                    <span className="ah-small ah-subtle">
                      Last active{" "}
                      <Time iso={past.find((s) => s.session_id === resume)?.last_activity ?? ""} />
                    </span>
                  </>
                )}
              </div>
            )}

            <div className="ah-stack" style={{ gap: 4 }}>
              <label htmlFor={promptField} className="ah-small">
                First prompt (optional)
              </label>
              <textarea
                id={promptField}
                className="ah-input as-composer-input"
                rows={4}
                value={prompt}
                disabled={pending}
                aria-invalid={promptTooLong}
                aria-describedby={promptHint}
                onChange={(event) => {
                  setPrompt(event.target.value);
                }}
              />
              <span id={promptHint} className="ah-small ah-subtle">
                {promptTooLong
                  ? `Too long: at most ${String(Math.floor(maxPromptBytes / 1024))} KiB.`
                  : needsPrompt
                    ? "The screenshot goes with the first prompt: write one."
                    : "Without a prompt the session waits for your first message."}
              </span>
              {workdir && workdir.skills.length > 0 && (
                <div className="ah-row ah-wrap" style={{ gap: 6 }} role="group" aria-label="Skills">
                  {workdir.skills.map((skill) => (
                    <Button
                      key={skill}
                      size="sm"
                      variant="ghost"
                      disabled={pending}
                      onClick={() => {
                        setPrompt((before) => withSkill(before, skill));
                      }}
                    >
                      /{skill}
                    </Button>
                  ))}
                </div>
              )}
            </div>

            {screenshot && (
              <div className="ah-stack" style={{ gap: 4 }}>
                <label htmlFor={attachField} className="ah-row ah-small" style={{ gap: 6 }}>
                  <input
                    id={attachField}
                    type="checkbox"
                    className="ah-check"
                    checked={attached}
                    disabled={pending || shot === null}
                    onChange={(event) => {
                      setAttach(event.target.checked);
                    }}
                  />
                  Attach a screenshot of the current screen
                </label>
                {shot === null ? (
                  <span className="ah-small ah-subtle">No screenshot was taken</span>
                ) : (
                  <img className="as-shot" src={shot} alt="Screenshot of the screen you shook" />
                )}
              </div>
            )}

            {pending && (
              <span role="status" className="ah-small">
                Starting the session…
              </span>
            )}
            {error && !pending && (
              <p role="alert" className="as-error ah-small">
                {error.title}
                {error.detail ? `: ${error.detail}` : ""}
              </p>
            )}
          </div>
          <div className="ah-dialog-foot">
            <Button disabled={pending} onClick={onCancel}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={!ready}>
              {pending ? "Starting…" : "Start session"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
