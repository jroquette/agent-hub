import { useId, useRef, useState } from "react";

import { Button } from "../../components";
import { ApiProblem } from "../../lib/api";
import { modeLabel, type AgentSessionStatus, type PermissionMode } from "./transcript";

/** The modes the web offers (D5): never bypassPermissions, dontAsk or auto. */
export const MODES: readonly PermissionMode[] = ["default", "acceptEdits", "plan"];
/** The user message limit's default (L3: 64 KiB of UTF-8). */
export const DEFAULT_MESSAGE_MAX_BYTES = 64 * 1024;

export interface SettingsChange {
  mode?: PermissionMode;
  model?: string;
}

export interface ComposerProps {
  status: AgentSessionStatus | null;
  mode: PermissionMode;
  model: string | null;
  /** The model aliases capabilities offer; the current model is added when it is another id. */
  models: readonly string[];
  onSend: (text: string) => Promise<unknown> | undefined;
  onInterrupt: () => Promise<unknown> | undefined;
  onSettings: (change: SettingsChange) => Promise<unknown> | undefined;
  /** Called as a message goes out: the chat pins the transcript to its bottom (AC-234.18). */
  onSending?: (() => void) | undefined;
  maxBytes?: number | undefined;
  /** Why nothing can be sent (log full, control off…); the session's end is detected on its own. */
  disabledReason?: string | null | undefined;
}

const bytesOf = (text: string) => new TextEncoder().encode(text).length;

function problemText(error: unknown, what: string): string {
  if (error instanceof ApiProblem)
    return error.detail ? `${error.title}: ${error.detail}` : error.title;
  return `Could not ${what}. Try again.`;
}

/**
 * The message box of a session (D10, AC-165.45): Enter sends, Shift+Enter starts a new line. Stop,
 * or Esc in the empty box, interrupts while a turn runs or waits on a permission (AC-234.21), once
 * until that interrupt answers, with Stop disabled and reading "Stopping…" meanwhile. The mode and model selectors post settings.
 */
export function Composer({
  status,
  mode,
  model,
  models,
  onSend,
  onInterrupt,
  onSettings,
  onSending,
  maxBytes = DEFAULT_MESSAGE_MAX_BYTES,
  disabledReason,
}: ComposerProps) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  // Shown, not only guarded: a POST that never settles leaves a visibly pending Stop.
  const [stoppingShown, setStoppingShown] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false);
  const stopping = useRef(false);
  const inputId = useId();
  const hintId = useId();
  const modeId = useId();
  const modelId = useId();

  const ended = status === "ended" || status === "failed";
  const reason = ended
    ? "This session has ended. Resume it to continue."
    : (disabledReason ?? null);
  const size = bytesOf(text);
  const tooLong = size > maxBytes;
  const canSend = reason === null && !sending && !tooLong && text.trim() !== "";
  const canStop = status === "running" || status === "waiting_permission";
  const currentModel = model ?? "default";
  const modelOptions = models.includes(currentModel) ? models : [...models, currentModel];

  const run = (action: () => Promise<unknown> | undefined, what: string, done?: () => void) => {
    setError(null);
    void Promise.resolve()
      .then(action)
      .catch((cause: unknown) => {
        setError(problemText(cause, what));
      })
      .finally(done);
  };

  const stop = () => {
    if (!canStop || stopping.current) return;
    stopping.current = true;
    setStoppingShown(true);
    run(onInterrupt, "stop the turn", () => {
      stopping.current = false;
      setStoppingShown(false);
    });
  };

  const send = () => {
    if (!canSend || busy.current) return;
    onSending?.();
    busy.current = true;
    setSending(true);
    setError(null);
    const message = text;
    void Promise.resolve()
      .then(() => onSend(message))
      .then(
        () => {
          setText((current) => (current === message ? "" : current));
        },
        (cause: unknown) => {
          setError(problemText(cause, "send the message"));
        },
      )
      .finally(() => {
        busy.current = false;
        setSending(false);
      });
  };

  return (
    <form
      className="as-composer"
      aria-label="Message composer"
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
    >
      <label htmlFor={inputId} className="ah-sr">
        Message Claude
      </label>
      <textarea
        id={inputId}
        className="ah-input as-composer-input"
        rows={3}
        value={text}
        placeholder={reason ?? "Message Claude"}
        disabled={reason !== null}
        aria-describedby={hintId}
        aria-invalid={tooLong}
        onChange={(event) => {
          setText(event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing) return;
          // Esc stops only from an empty box (no menu exists yet): typed text keeps its Esc.
          if (event.key === "Escape" && text === "" && canStop) {
            event.preventDefault();
            stop();
          }
          if (event.key !== "Enter" || event.shiftKey) return;
          event.preventDefault();
          send();
        }}
      />
      <div className="as-composer-bar">
        <label htmlFor={modeId} className="ah-row ah-small" style={{ gap: 4 }}>
          <span className="ah-subtle">Mode</span>
          <select
            id={modeId}
            className="ah-input as-select"
            value={mode}
            disabled={ended}
            onChange={(event) => {
              const next = MODES.find((m) => m === event.target.value);
              if (next) run(() => onSettings({ mode: next }), "change the mode");
            }}
          >
            {MODES.map((m) => (
              <option key={m} value={m}>
                {modeLabel(m)}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor={modelId} className="ah-row ah-small" style={{ gap: 4 }}>
          <span className="ah-subtle">Model</span>
          <select
            id={modelId}
            className="ah-input as-select"
            value={currentModel}
            disabled={ended}
            onChange={(event) => {
              const next = event.target.value;
              run(() => onSettings({ model: next }), "change the model");
            }}
          >
            {modelOptions.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
        <span id={hintId} className="ah-small ah-subtle ah-grow">
          {tooLong
            ? `Too long: ${String(Math.ceil(size / 1024))} KiB of ${String(Math.floor(maxBytes / 1024))} KiB`
            : "Enter to send, Shift+Enter for a new line"}
        </span>
        <Button icon="circle-stop" disabled={!canStop || stoppingShown} onClick={stop}>
          {stoppingShown ? "Stopping…" : "Stop"}
        </Button>
        <Button type="submit" variant="primary" icon="arrow-up" disabled={!canSend}>
          {sending ? "Sending…" : "Send"}
        </Button>
      </div>
      {error && (
        <p className="ah-small as-error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
