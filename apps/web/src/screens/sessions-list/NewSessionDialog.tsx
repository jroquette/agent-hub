import "../agent-session/agent-session.css";

import { useId, useState, type KeyboardEvent } from "react";

import type { components } from "../../api/schema";
import { Button, Dialog, Time } from "../../components";
import { readStored, writeStored } from "../../lib/storage";
import type { ApiProblem } from "../../lib/api";
import { offeredModes, DEFAULT_MESSAGE_MAX_BYTES } from "../agent-session/Composer";
import { modeLabel, type PermissionMode } from "../agent-session/model";

type Schemas = components["schemas"];
export type Workdir = Schemas["Workdir"];
export type DriverCapabilities = Schemas["DriverCapabilities"];
export type CreateAgentSession = Schemas["CreateAgentSession"];
export type AgentSession = Schemas["AgentSession"];

/** The screen a shake captured (AGH-260), or the capture that failed. */
export type ShakeScreenshot = { dataUrl: string } | { failed: true };

/** A model id the CLI may take besides the aliases (L6); the server checks the same pattern. */
export const MODEL_PATTERN = /^[A-Za-z0-9._\-[\]]{1,64}$/;
const OTHER_MODEL = "__other__";
/** The folder last started in, per project (AC-234.14). */
const workdirKey = (project: string) => `ah.sessions.workdir.${project}`;

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
  /** The projects "Where" offers; with fewer than two the project is only named. */
  projects?: readonly string[] | undefined;
  /** Called with the project chosen in "Where"; the caller then passes its folders. */
  onProjectChange?: ((project: string) => void) | undefined;
  /** The folders a session may start in, never a free path (D6); undefined while they load. */
  workdirs: readonly Workdir[] | undefined;
  /** Why the folders could not be listed, said in place of the picker. */
  workdirsProblem?: string | undefined;
  capabilities: DriverCapabilities;
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
  /**
   * The ended session to fork (AC-234.15): a new conversation from it in its folder, with its mode
   * and model. A message in its chat resumes it in place (ADR 0036).
   */
  forkOf?: AgentSession | undefined;
}

/** The folder to preselect: the given one, else the last used for the project, else the first. */
function preferredWorkdir(project: string, workdirs: readonly Workdir[], initial?: string) {
  const listed = (id: string | null | undefined) =>
    workdirs.some((w) => w.workdir_id === id) ? id : undefined;
  return listed(initial) ?? listed(readStored(workdirKey(project))) ?? workdirs[0]?.workdir_id;
}

/**
 * "New session" (D10, AC-165.42, AC-234.14): where to start (project › one of the listed folders)
 * and the prompt; the mode (never bypass) and the model alias or id wait in "Options".
 */
export function NewSessionDialog({
  project,
  projects = [],
  onProjectChange,
  workdirs,
  workdirsProblem,
  capabilities,
  pending,
  error,
  maxPromptBytes = DEFAULT_MESSAGE_MAX_BYTES,
  onSubmit,
  onCancel,
  screenshot,
  initialWorkdirId,
  initialMode,
  note,
  forkOf,
}: NewSessionDialogProps) {
  const [picked, setPicked] = useState<string | null>(null);
  // Only an offered mode starts checked: a built app never offers auto (ADR 0036), so a fork of an
  // auto session started in the playground falls back to the default, shown checked under Options.
  const [mode, setMode] = useState<PermissionMode>(() => {
    const wanted = forkOf?.mode ?? initialMode ?? "default";
    return offeredModes().includes(wanted) ? wanted : "default";
  });
  const shot = screenshot && "dataUrl" in screenshot ? screenshot.dataUrl : null;
  const [attach, setAttach] = useState(shot !== null);
  // A fork keeps its session's model, as "Other model id" when the capabilities do not list it.
  const kept = forkOf?.model ?? null;
  const [model, setModel] = useState(
    kept === null
      ? (capabilities.models[0] ?? "default")
      : capabilities.models.includes(kept)
        ? kept
        : OTHER_MODEL,
  );
  const [otherModel, setOtherModel] = useState(
    kept !== null && !capabilities.models.includes(kept) ? kept : "",
  );
  const [prompt, setPrompt] = useState("");
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [firstProject] = useState(project);
  const modeName = useId();
  const whereId = useId();
  const optionsId = useId();
  const summaryId = useId();
  const reasonId = useId();
  const modelField = useId();
  const otherField = useId();
  const otherHint = useId();
  const promptField = useId();
  const promptHint = useId();
  const attachField = useId();
  const forkId = useId();

  const folders = workdirs ?? [];
  const preferred = preferredWorkdir(
    project,
    folders,
    project === firstProject ? initialWorkdirId : undefined,
  );
  const workdir =
    folders.find((w) => w.workdir_id === picked) ?? folders.find((w) => w.workdir_id === preferred);
  const workdirId = workdir?.workdir_id ?? "";
  // A fork starts in its session's own folder: the server finds the Claude session there.
  const where = forkOf
    ? { project: forkOf.project, workdir_id: forkOf.workdir_id }
    : workdir && { project, workdir_id: workdir.workdir_id };

  const chosenModel = model === OTHER_MODEL ? otherModel.trim() : model;
  const modelValid = MODEL_PATTERN.test(chosenModel);
  const promptBytes = new TextEncoder().encode(prompt).length;
  const promptTooLong = promptBytes > maxPromptBytes;
  const attached = attach && shot !== null;
  const needsPrompt = attached && prompt.trim() === "";
  const reason = pending
    ? null
    : !capabilities.available
      ? "Sessions cannot start on this machine."
      : !forkOf && workdirs === undefined && !workdirsProblem
        ? "Waiting for the working folders."
        : !where
          ? "No working folder to start in."
          : !modelValid
            ? "Options: the model id is not valid."
            : promptTooLong
              ? "The prompt is too long."
              : needsPrompt
                ? "Write a prompt to send the screenshot."
                : null;
  const ready = !pending && reason === null;

  const submit = () => {
    if (!ready || !where) return;
    if (!forkOf) writeStored(workdirKey(project), where.workdir_id);
    const text = prompt.trim();
    const body: CreateAgentSession = {
      ...where,
      mode,
      model: chosenModel,
      prompt: text ? text : null,
      resume_session_id: forkOf?.claude_session_id ?? null,
      fork: forkOf !== undefined,
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

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey) || event.nativeEvent.isComposing)
      return;
    event.preventDefault();
    submit();
  };

  return (
    <Dialog
      title={forkOf ? "Fork session" : "New session"}
      onClose={onCancel}
      pending={pending}
      initialFocus="textarea"
      className="as-new-dialog"
      footer={
        <>
          {reason && (
            <span id={reasonId} className="ah-small ah-muted ah-grow">
              {reason}
            </span>
          )}
          <Button disabled={pending} onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={!ready}
            aria-describedby={reason ? reasonId : undefined}
            onClick={submit}
          >
            {pending ? "Starting…" : "Start session"}
          </Button>
        </>
      }
    >
      {/* Ctrl/Cmd+Enter from any field starts the session; the controls keep their own keys. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <form
        className="ah-stack"
        style={{ gap: 12 }}
        onKeyDown={onKeyDown}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
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

        {forkOf ? (
          <div role="group" aria-labelledby={forkId} className="ah-stack" style={{ gap: 4 }}>
            <span id={forkId} className="ah-small">
              Fork
            </span>
            <b>{forkOf.title ?? "Untitled session"}</b>
            <span className="ah-small ah-muted">
              {forkOf.project} › <span className="ah-mono">{forkOf.workdir_label}</span> ·{" "}
              <span>
                {forkOf.status === "failed" ? "Failed" : "Ended"}{" "}
                <Time iso={forkOf.ended_at ?? forkOf.updated_at} />
              </span>
            </span>
            <span className="ah-small ah-subtle">
              A new conversation that starts from this one and keeps this one unchanged.
            </span>
          </div>
        ) : (
          <div role="group" aria-labelledby={whereId} className="ah-stack" style={{ gap: 4 }}>
            <span id={whereId} className="ah-small">
              Where
            </span>
            <div className="ah-row ah-wrap" style={{ gap: 6 }}>
              {projects.length > 1 ? (
                <select
                  aria-label="Project"
                  className="ah-input as-select"
                  value={project}
                  disabled={pending}
                  onChange={(event) => {
                    setPicked(null);
                    onProjectChange?.(event.target.value);
                  }}
                >
                  {projects.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="ah-small">{project}</span>
              )}
              <span aria-hidden="true" className="ah-subtle">
                ›
              </span>
              {workdirs === undefined && !workdirsProblem ? (
                <span className="ah-small ah-muted">Loading the working folders…</span>
              ) : folders.length === 0 ? (
                <span className="ah-small ah-muted">
                  {workdirsProblem ?? `No working folder found for ${project}.`}
                </span>
              ) : (
                <select
                  aria-label="Working folder"
                  className="ah-input as-select ah-grow"
                  value={workdirId}
                  disabled={pending}
                  onChange={(event) => {
                    setPicked(event.target.value);
                  }}
                >
                  {folders.map((w) => (
                    <option key={w.workdir_id} value={w.workdir_id}>
                      {workdirText(w)}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>
        )}
        <div className="ah-stack" style={{ gap: 4 }}>
          <label htmlFor={promptField} className="ah-small">
            Prompt
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
                : "Without a prompt the session waits for your first message. Ctrl+Enter or ⌘+Enter starts it."}
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

        <div className="ah-stack" style={{ gap: 8 }}>
          <div className="ah-row" style={{ gap: 6 }}>
            <Button
              size="sm"
              variant="ghost"
              icon={optionsOpen ? "chevron-down" : "chevron-right"}
              aria-expanded={optionsOpen}
              aria-controls={optionsOpen ? optionsId : undefined}
              aria-describedby={summaryId}
              onClick={() => {
                setOptionsOpen((open) => !open);
              }}
            >
              Options
            </Button>
            <span id={summaryId} className="ah-small ah-muted">
              {`${modeLabel(mode)} · ${chosenModel || "no model id"}`}
            </span>
          </div>
          {optionsOpen && (
            <div id={optionsId} className="ah-stack" style={{ gap: 12 }}>
              <fieldset className="as-fieldset" disabled={pending}>
                <legend className="ah-small">Mode</legend>
                {offeredModes().map((m) => (
                  <label key={m} className="as-radio">
                    <input
                      type="radio"
                      name={modeName}
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
            </div>
          )}
        </div>
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
      </form>
    </Dialog>
  );
}
