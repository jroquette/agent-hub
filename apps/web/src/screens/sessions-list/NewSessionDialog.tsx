import "../agent-session/agent-session.css";

import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

import type { components } from "../../api/schema";
import {
  AttachButton,
  AttachmentList,
  Button,
  Dialog,
  Icon,
  Time,
  useAttachmentDrop,
  useMessageAttachments,
  type AttachedImage,
} from "../../components";
import type { ApiProblem } from "../../lib/api";
import { cx } from "../../lib/cx";
import { fileBody } from "../../lib/messageFile";
import { screenshotBody } from "../../lib/pastedImage";
import { readStored, writeStored } from "../../lib/storage";
import { useAutoGrow } from "../../lib/useAutoGrow";
import { offeredModes, DEFAULT_MESSAGE_MAX_BYTES } from "../agent-session/Composer";
import { modeLabel, type PermissionMode } from "../agent-session/model";
import { useSlashMenu, type SlashOption } from "../agent-session/SlashMenu";

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
/** The prompt grows with its text up to this share of the viewport, then scrolls. */
const PROMPT_HEIGHT_SHARE = 0.35;
/** The shake's screenshot in the attachments row, apart from the images added by hand. */
const SHOT_KEY = -1;
const SHOT_ALT = "Screenshot of the screen you shook";

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
  /** The dialog's title in place of "New session", such as "Start ticket". */
  title?: string | undefined;
  /** The prompt the field opens with, such as `/fix ` for a ticket. */
  initialPrompt?: string | undefined;
}

/** The folder to preselect: the given one, else the last used for the project, else the first. */
function preferredWorkdir(project: string, workdirs: readonly Workdir[], initial?: string) {
  const listed = (id: string | null | undefined) =>
    workdirs.some((w) => w.workdir_id === id) ? id : undefined;
  return listed(initial) ?? listed(readStored(workdirKey(project))) ?? workdirs[0]?.workdir_id;
}

/**
 * "New session" (D10, AC-165.42, AC-234.14): where to start (project › one of the listed folders)
 * and the first prompt, in the chat's message card: images and files pasted, dropped or picked
 * go with it, `/` lists the folder's skills, and the mode (never bypass) and the model sit in the
 * card's bar as in the chat.
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
  title,
  initialPrompt,
}: NewSessionDialogProps) {
  const [picked, setPicked] = useState<string | null>(null);
  // Only an offered mode starts checked: a built app never offers auto (ADR 0036), so a fork of an
  // auto session started in the playground falls back to the default.
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
  const [prompt, setPrompt] = useState(initialPrompt ?? "");
  const [attachError, setAttachError] = useState<string | null>(null);
  const [firstProject] = useState(project);
  // The screenshot's marked-up copy, once edited in the lightbox; it is the one sent.
  const [marked, setMarked] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement | null>(null);
  const focusBox = () => box.current?.focus({ preventScroll: true });
  const attachments = useMessageAttachments({
    acceptsImages: true,
    acceptsFiles: true,
    disabled: pending,
    onError: setAttachError,
  });
  const { dragging, dropProps } = useAttachmentDrop(attachments, {
    disabled: pending,
    onAdded: focusBox,
  });
  useAutoGrow(box, prompt, PROMPT_HEIGHT_SHARE);
  const whereId = useId();
  const reasonId = useId();
  const modeField = useId();
  const modelField = useId();
  const otherField = useId();
  const otherHint = useId();
  const promptField = useId();
  const promptHint = useId();
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
  const needsPrompt = (attached || attachments.count > 0) && prompt.trim() === "";
  const reason = pending
    ? null
    : !capabilities.available
      ? "Sessions cannot start on this machine."
      : !forkOf && workdirs === undefined && !workdirsProblem
        ? "Waiting for the working folders."
        : !where
          ? "No working folder to start in."
          : !modelValid
            ? "The model id is not valid."
            : promptTooLong
              ? "The prompt is too long."
              : attachments.reading > 0
                ? "Wait for the files to be read."
                : needsPrompt
                  ? "Write a prompt to send the attachments."
                  : null;
  const ready = !pending && reason === null;

  const submit = () => {
    if (!ready || !where) return;
    if (!forkOf) writeStored(workdirKey(project), where.workdir_id);
    const text = prompt.trim();
    const { images, files } = attachments;
    onSubmit({
      ...where,
      mode,
      model: chosenModel,
      prompt: text ? text : null,
      resume_session_id: forkOf?.claude_session_id ?? null,
      fork: forkOf !== undefined,
      ...(attached ? { screenshot: screenshotBody(marked ?? shot) } : {}),
      ...(images.length > 0
        ? { screenshots: images.map((image) => screenshotBody(image.url)) }
        : {}),
      ...(files.length > 0 ? { files: files.map((one) => fileBody(one.file)) } : {}),
    });
  };

  // The folder's skills fill the `/` menu, as the hub's do in a chat.
  const skills: SlashOption[] = (workdir?.skills ?? []).map((skill) => ({
    command: `/${skill}`,
    hub: false,
    description: null,
  }));
  const [caret, setCaret] = useState<number | null>(null);
  const placeCaret = useRef<number | null>(null);
  const slash = useSlashMenu(
    pending ? "" : prompt,
    Math.min(caret ?? prompt.length, prompt.length),
    skills,
    (next, at) => {
      placeCaret.current = at;
      setCaret(at);
      setPrompt(next);
    },
  );
  useLayoutEffect(() => {
    const at = placeCaret.current;
    if (at === null || !box.current) return;
    placeCaret.current = null;
    box.current.setSelectionRange(at, at);
  }, [prompt]);

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey) || event.nativeEvent.isComposing)
      return;
    event.preventDefault();
    submit();
  };

  // The shake's screenshot leads the attachments row; once marked up, its new copy is shown.
  const images: AttachedImage[] = [
    ...(attached ? [{ key: SHOT_KEY, url: marked ?? shot, alt: SHOT_ALT }] : []),
    ...attachments.images,
  ];
  const modes = offeredModes();

  return (
    <Dialog
      title={forkOf ? "Fork session" : (title ?? "New session")}
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
            icon="arrow-up"
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
        className="as-new-form"
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
          <div role="group" aria-labelledby={forkId} className="as-new-where as-new-fork">
            <span id={forkId} className="as-new-label">
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
          <div role="group" aria-labelledby={whereId} className="as-new-where">
            <span id={whereId} className="as-new-label">
              Where
            </span>
            <div className="as-new-where-row">
              {projects.length > 1 ? (
                <label className="as-pill as-new-pill">
                  <Icon name="folder-kanban" size="sm" />
                  <select
                    aria-label="Project"
                    className="as-pill-select"
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
                  <span className="as-pill-value" aria-hidden="true">
                    {project}
                  </span>
                  <Icon name="chevron-down" size="sm" className="as-pill-caret" />
                </label>
              ) : (
                <span className="as-new-project">
                  <Icon name="folder-kanban" size="sm" />
                  {project}
                </span>
              )}
              <Icon name="chevron-right" size="sm" className="ah-subtle" />
              {workdirs === undefined && !workdirsProblem ? (
                <span className="ah-small ah-muted">Loading the working folders…</span>
              ) : folders.length === 0 ? (
                <span className="ah-small ah-muted">
                  {workdirsProblem ?? `No working folder found for ${project}.`}
                </span>
              ) : (
                <label className="as-pill as-new-pill as-new-folder">
                  <Icon name={workdir?.kind === "worktree" ? "git-branch" : "folder"} size="sm" />
                  <select
                    aria-label="Working folder"
                    className="as-pill-select"
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
                  <Icon name="chevron-down" size="sm" className="as-pill-caret" />
                </label>
              )}
            </div>
          </div>
        )}

        <div className="as-new-prompt">
          <label htmlFor={promptField} className="as-new-label">
            Prompt
          </label>
          {/* Files dropped anywhere on the card join the first prompt; the keyboard has Attach. */}
          <div
            className={cx("as-composer as-new-composer", dragging && "as-composer-drop")}
            {...dropProps}
          >
            <AttachmentList
              images={images}
              files={attachments.files}
              reading={attachments.reading}
              label="Attached to the first prompt"
              onRemoveImage={(key) => {
                if (key === SHOT_KEY) setAttach(false);
                else attachments.removeImage(key);
                focusBox();
              }}
              onRemoveFile={(key) => {
                attachments.removeFile(key);
                focusBox();
              }}
              onReplaceImage={(key, url) => {
                if (key === SHOT_KEY) setMarked(url);
                else attachments.replaceImage(key, url);
              }}
            />
            {slash.menu}
            {/* A textbox's activedescendant is not announced everywhere: the menu says what it holds. */}
            <span className="ah-sr" aria-live="polite" aria-atomic="true">
              {slash.announcement}
            </span>
            <textarea
              id={promptField}
              ref={box}
              className="ah-input as-composer-input"
              rows={3}
              value={prompt}
              disabled={pending}
              placeholder={
                images.length > 0
                  ? "Say what Claude should look at in the image"
                  : attachments.files.length > 0
                    ? "Say what Claude should do with the file"
                    : skills.length > 0
                      ? "What should Claude do? Type / for the folder's skills"
                      : "What should Claude do?"
              }
              aria-invalid={promptTooLong}
              aria-describedby={promptHint}
              {...slash.inputProps}
              onChange={(event) => {
                setPrompt(event.target.value);
                setCaret(event.target.selectionStart);
              }}
              onSelect={(event) => {
                setCaret(event.currentTarget.selectionStart);
              }}
              onPaste={(event) => {
                if (!attachments.takes(event.clipboardData)) return;
                // A copied file may also carry its name as text: only the file is pasted.
                event.preventDefault();
                attachments.add(event.clipboardData);
              }}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing) return;
                // The open `/` menu takes its keys first (Esc closes it, Enter inserts): the
                // dialog never sees them, so Esc keeps the dialog open and Enter never starts.
                if (slash.onKeyDown(event)) event.stopPropagation();
              }}
            />
            <div className="as-composer-bar">
              <AttachButton
                attachments={attachments}
                disabled={pending}
                className="as-composer-attach"
                onAdded={focusBox}
              />
              <div className="as-composer-settings">
                <label
                  htmlFor={modeField}
                  className="as-pill"
                  data-mode={mode}
                  title={MODE_HINT[mode]}
                >
                  <Icon name="shield" size="sm" />
                  <span className="ah-sr">Mode</span>
                  <select
                    id={modeField}
                    className="as-pill-select"
                    value={mode}
                    disabled={pending}
                    onChange={(event) => {
                      const next = modes.find((m) => m === event.target.value);
                      if (next) setMode(next);
                    }}
                  >
                    {modes.map((m) => (
                      <option key={m} value={m}>
                        {modeLabel(m)}
                      </option>
                    ))}
                  </select>
                  <span className="as-pill-value" aria-hidden="true">
                    {modeLabel(mode)}
                  </span>
                  <Icon name="chevron-down" size="sm" className="as-pill-caret" />
                </label>
                <label htmlFor={modelField} className="as-pill" title="Model">
                  <Icon name="cpu" size="sm" />
                  <span className="ah-sr">Model</span>
                  <select
                    id={modelField}
                    className="as-pill-select"
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
                  <span className="as-pill-value" aria-hidden="true">
                    {model === OTHER_MODEL ? "Other model id…" : model}
                  </span>
                  <Icon name="chevron-down" size="sm" className="as-pill-caret" />
                </label>
              </div>
            </div>
          </div>
          <span
            id={promptHint}
            className="as-new-hint"
            data-warn={promptTooLong || needsPrompt || undefined}
          >
            {promptTooLong
              ? `Too long: at most ${String(Math.floor(maxPromptBytes / 1024))} KiB.`
              : needsPrompt
                ? "The attachments go with the first prompt: write one."
                : "Without a prompt the session waits for your first message. Ctrl+Enter or ⌘+Enter starts it."}
          </span>
          <span className="as-new-hint">
            <b>{modeLabel(mode)}.</b> {MODE_HINT[mode]} Paste or drop images, PDFs and text files.
          </span>
          {attachError && (
            <p role="alert" className="as-error ah-small">
              {attachError}
            </p>
          )}
        </div>

        {screenshot && !attached && (
          <div className="ah-row" style={{ gap: 6 }}>
            {shot === null ? (
              <span className="ah-small ah-subtle">No screenshot was taken</span>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                icon="plus"
                disabled={pending}
                onClick={() => {
                  setAttach(true);
                  focusBox();
                }}
              >
                Attach the screenshot again
              </Button>
            )}
          </div>
        )}

        {model === OTHER_MODEL && (
          <div className="ah-stack" style={{ gap: 4 }}>
            <label htmlFor={otherField} className="as-new-label">
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
          </div>
        )}

        {workdir && workdir.skills.length > 0 && (
          <div className="as-new-skills" role="group" aria-label="Skills">
            <span className="as-new-label" aria-hidden="true">
              Skills
            </span>
            {workdir.skills.map((skill) => (
              <Button
                key={skill}
                size="sm"
                variant="ghost"
                className="as-new-skill"
                disabled={pending}
                onClick={() => {
                  setPrompt((before) => withSkill(before, skill));
                  focusBox();
                }}
              >
                /{skill}
              </Button>
            ))}
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
      </form>
    </Dialog>
  );
}
