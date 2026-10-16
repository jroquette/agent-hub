import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";

import { Button, Icon, ScreenshotThumb } from "../../components";
import { ApiProblem } from "../../lib/api";
import { cx } from "../../lib/cx";
import { imageFiles, imageToPng, MAX_MESSAGE_IMAGES } from "../../lib/pastedImage";
import { servedCheckout } from "../../lib/devCheckout";
import { useSlashMenu } from "./SlashMenu";
import { useDraft } from "./useDraft";
import { modeLabel, type AgentSessionStatus, type PermissionMode } from "./model";

/** The modes the web offers (D5): never bypassPermissions or dontAsk. */
export const MODES: readonly PermissionMode[] = ["default", "acceptEdits", "plan"];

/** The modes to offer: `auto` too in the dev app of `make playground`, where the agent works alone. */
export function offeredModes(): readonly PermissionMode[] {
  return servedCheckout() === null ? MODES : [...MODES, "auto"];
}
/** The user message limit's default (`--message-max-bytes`: 1 MiB of UTF-8). */
export const DEFAULT_MESSAGE_MAX_BYTES = 1024 * 1024;
/** The composer grows with its text up to this share of the viewport, then scrolls (AC-234.26). */
const MAX_HEIGHT_SHARE = 0.4;
/** Safari sends the Enter that ends an IME composition after `compositionend`. */
const AFTER_COMPOSITION_MS = 500;

/** On a touch screen Enter is a new line and the Send button sends (AC-234.26). */
const coarsePointer = () =>
  typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;

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
  /** Sends the text, with the PNG data URLs of the images pasted in it (`acceptsImages`). */
  onSend: (text: string, screenshots: readonly string[]) => Promise<unknown> | undefined;
  onInterrupt: () => Promise<unknown> | undefined;
  onSettings: (change: SettingsChange) => Promise<unknown> | undefined;
  /** Called as a message goes out: the chat pins the transcript to its bottom (AC-234.18). */
  onSending?: (() => void) | undefined;
  maxBytes?: number | undefined;
  /** What the `/` menu lists: the session's slash commands and skills (AC-234.28). */
  commands?: readonly string[] | undefined;
  /** What ArrowUp in the empty box recalls: the last prompt sent (AC-234.29). */
  lastPrompt?: string | null | undefined;
  /** Receives the message box, so the chat can focus it (Shift+Esc). */
  inputRef?: ((element: HTMLTextAreaElement | null) => void) | undefined;
  /** The session whose draft this browser keeps (`ah.chat.draft.<id>`); none keeps nothing. */
  draftId?: string | null | undefined;
  /** Take focus on open (the chat asks unless a permission is pending, AC-234.26). */
  focusOnOpen?: boolean | undefined;
  /** Why nothing can be sent (log full, control off…); the session's end is detected on its own. */
  disabledReason?: string | null | undefined;
  /** An ended session a message resumes in place (Claude still holds its conversation). */
  resumable?: boolean | undefined;
  /** Images may be pasted, dropped or picked into the message (up to `MAX_MESSAGE_IMAGES`). */
  acceptsImages?: boolean | undefined;
}

interface PastedImage {
  key: number;
  url: string;
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
  commands = [],
  lastPrompt = null,
  inputRef,
  draftId = null,
  focusOnOpen = false,
  resumable = false,
  acceptsImages = false,
}: ComposerProps) {
  const { text, setText, accepted } = useDraft(draftId);
  const [images, setImages] = useState<PastedImage[]>([]);
  const [reading, setReading] = useState(0);
  const [dragging, setDragging] = useState(false);
  const imageKeys = useRef(0);
  const filePicker = useRef<HTMLInputElement | null>(null);
  const [sending, setSending] = useState(false);
  // Shown, not only guarded: a POST that never settles leaves a visibly pending Stop.
  const [stoppingShown, setStoppingShown] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false);
  const box = useRef<HTMLTextAreaElement | null>(null);
  const composing = useRef(false);
  const composedAt = useRef(-Infinity);
  const stopping = useRef(false);
  const inputId = useId();
  const hintId = useId();
  const modeId = useId();
  const modelId = useId();

  const ended = status === "ended" || status === "failed";
  const resumes = ended && resumable && !disabledReason;
  const reason =
    ended && !resumes
      ? "This session has ended. Start a new session to continue."
      : (disabledReason ?? null);
  const size = bytesOf(text);
  const tooLong = size > maxBytes;
  const canSend = reason === null && !sending && !tooLong && reading === 0 && text.trim() !== "";
  const needsText = images.length > 0 && text.trim() === "";
  const canStop = status === "running" || status === "waiting_permission";
  const currentModel = model ?? "default";
  const modelOptions = models.includes(currentModel) ? models : [...models, currentModel];
  // A mode set elsewhere (`auto` outside the playground) is shown, but cannot be picked here.
  const modes = offeredModes();
  const unofferedMode = modes.includes(mode) ? null : mode;

  const attachBox = useCallback(
    (element: HTMLTextAreaElement | null) => {
      box.current = element;
      inputRef?.(element);
    },
    [inputRef],
  );
  const focusBox = () => box.current?.focus({ preventScroll: true });
  const slash = useSlashMenu(reason === null ? text : "", commands, setText);
  // On open only: a permission that arrives later never takes focus away from here.
  const focusOnMount = useRef(focusOnOpen);
  useEffect(() => {
    if (focusOnMount.current) box.current?.focus({ preventScroll: true });
  }, []);

  // One layout read per fit; a window resize moves the 40vh cap, so it fits again.
  const fit = useCallback(() => {
    const element = box.current;
    if (!element) return;
    const max = Math.floor(window.innerHeight * MAX_HEIGHT_SHARE);
    element.style.height = "auto";
    const content = element.scrollHeight;
    element.style.height = `${String(Math.min(content, max))}px`;
    element.style.overflowY = content > max ? "auto" : "hidden";
  }, []);
  useLayoutEffect(fit, [fit, text]);
  useEffect(() => {
    window.addEventListener("resize", fit);
    return () => {
      window.removeEventListener("resize", fit);
    };
  }, [fit]);

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

  // Each image is read and turned into a PNG under the size limit; past the limit, it is refused.
  const addImages = (files: readonly File[]) => {
    if (!acceptsImages || reason !== null || files.length === 0) return;
    const room = MAX_MESSAGE_IMAGES - images.length - reading;
    const taken = files.slice(0, Math.max(0, room));
    setError(
      taken.length < files.length
        ? `A message takes up to ${String(MAX_MESSAGE_IMAGES)} images.`
        : null,
    );
    for (const file of taken) {
      setReading((count) => count + 1);
      imageToPng(file)
        .then((url) => {
          imageKeys.current += 1;
          const key = imageKeys.current;
          setImages((before) => [...before, { key, url }]);
        })
        .catch(() => {
          setError("Could not read that image. Try another one.");
        })
        .finally(() => {
          setReading((count) => count - 1);
        });
    }
  };

  const send = () => {
    if (!canSend || busy.current) return;
    onSending?.();
    focusBox(); // Send by click keeps typing where it was.
    busy.current = true;
    setSending(true);
    setError(null);
    const message = text;
    const sent = images;
    void Promise.resolve()
      .then(() =>
        onSend(
          message,
          sent.map((image) => image.url),
        ),
      )
      .then(
        () => {
          accepted(message);
          // Images pasted while it was sending stay for the next message.
          setImages((now) => now.filter((image) => !sent.includes(image)));
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
    // An image dropped anywhere on the composer joins the message; the keyboard has the picker.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <form
      className={cx("as-composer", dragging && "as-composer-drop")}
      aria-label="Message composer"
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
      onDragOver={(event) => {
        if (!acceptsImages || reason !== null || !event.dataTransfer.types.includes("Files"))
          return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
        setDragging(true);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(event) => {
        if (!acceptsImages) return;
        event.preventDefault();
        setDragging(false);
        addImages(imageFiles(event.dataTransfer));
        focusBox();
      }}
    >
      {(images.length > 0 || reading > 0) && (
        <ul className="as-composer-images" aria-label="Images in this message">
          {images.map((image, index) => (
            <li key={image.key} className="as-composer-image">
              <ScreenshotThumb
                className="as-composer-thumb"
                src={image.url}
                alt={`Image ${String(index + 1)}`}
                onSave={(url) => {
                  setImages((before) =>
                    before.map((one) => (one.key === image.key ? { ...one, url } : one)),
                  );
                }}
              />
              <button
                type="button"
                className="as-composer-image-remove"
                aria-label={`Remove image ${String(index + 1)}`}
                title="Remove"
                onClick={() => {
                  setImages((before) => before.filter((one) => one.key !== image.key));
                  focusBox();
                }}
              >
                <Icon name="x" size="sm" />
              </button>
            </li>
          ))}
          {reading > 0 && (
            <li className="as-composer-image as-composer-image-reading" aria-live="polite">
              <Icon name="loader" size="sm" className="as-spin" />
              <span className="ah-sr">Reading the image…</span>
            </li>
          )}
        </ul>
      )}
      {slash.menu}
      {/* A textbox's activedescendant is not announced everywhere: the menu says what it holds. */}
      <span className="ah-sr" aria-live="polite" aria-atomic="true">
        {slash.announcement}
      </span>
      <label htmlFor={inputId} className="ah-sr">
        Message Claude
      </label>
      <textarea
        id={inputId}
        ref={attachBox}
        className="ah-input as-composer-input"
        rows={3}
        value={text}
        placeholder={
          reason ??
          (resumes
            ? "This session has ended. Send a message to resume it."
            : images.length > 0
              ? "Say what Claude should look at in the image"
              : "Message Claude")
        }
        disabled={reason !== null}
        aria-describedby={hintId}
        aria-invalid={tooLong}
        {...slash.inputProps}
        onChange={(event) => {
          setText(event.target.value);
        }}
        onPaste={(event) => {
          const files = acceptsImages ? imageFiles(event.clipboardData) : [];
          if (files.length === 0) return;
          // A copied image may also carry its file name as text: only the image is pasted.
          event.preventDefault();
          addImages(files);
        }}
        onCompositionStart={() => {
          composing.current = true;
        }}
        onCompositionEnd={() => {
          composing.current = false;
          composedAt.current = performance.now();
        }}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing || composing.current) return;
          // The open `/` menu takes its keys first: Esc closes it, Enter inserts, never sends.
          if (slash.onKeyDown(event)) return;
          const plain = !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey;
          // Esc stops only from an empty box: typed text keeps its Esc (Shift+Esc is the chat's).
          if (event.key === "Escape" && plain && text === "" && canStop) {
            event.preventDefault();
            stop();
          }
          if (event.key === "ArrowUp" && plain && text === "" && lastPrompt) {
            event.preventDefault();
            setText(lastPrompt);
          }
          // Ctrl/Cmd+Alt+Enter answers a permission (the chat's chord), never sends; Alt+Enter sends.
          const chord = event.altKey && (event.ctrlKey || event.metaKey);
          if (event.key !== "Enter" || event.shiftKey || chord || coarsePointer()) return;
          event.preventDefault();
          if (performance.now() - composedAt.current >= AFTER_COMPOSITION_MS) send();
        }}
      />
      <div className="as-composer-bar">
        <div className="as-composer-settings">
          <label htmlFor={modeId} className="as-pill" data-mode={mode} title="Permission mode">
            <Icon name="shield" size="sm" />
            <span className="ah-sr">Mode</span>
            <select
              id={modeId}
              className="as-pill-select"
              value={mode}
              disabled={ended}
              onChange={(event) => {
                const next = modes.find((m) => m === event.target.value);
                if (next) run(() => onSettings({ mode: next }), "change the mode");
              }}
            >
              {modes.map((m) => (
                <option key={m} value={m}>
                  {modeLabel(m)}
                </option>
              ))}
              {unofferedMode && (
                <option value={unofferedMode} disabled>
                  {modeLabel(unofferedMode)}
                </option>
              )}
            </select>
            <Icon name="chevron-down" size="sm" className="as-pill-caret" />
          </label>
          <label htmlFor={modelId} className="as-pill" title="Model">
            <Icon name="cpu" size="sm" />
            <span className="ah-sr">Model</span>
            <select
              id={modelId}
              className="as-pill-select"
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
            <Icon name="chevron-down" size="sm" className="as-pill-caret" />
          </label>
        </div>
        <div className="as-composer-actions">
          {acceptsImages && (
            <>
              <input
                ref={filePicker}
                type="file"
                accept="image/*"
                multiple
                hidden
                tabIndex={-1}
                onChange={(event) => {
                  addImages(imageFiles(event.target));
                  event.target.value = "";
                  focusBox();
                }}
              />
              <Button
                size="sm"
                variant="ghost"
                icon="plus"
                className="as-composer-attach"
                disabled={reason !== null || images.length + reading >= MAX_MESSAGE_IMAGES}
                aria-label="Add an image"
                title="Add an image (or paste or drop one in the box)"
                onClick={() => filePicker.current?.click()}
              >
                Image
              </Button>
            </>
          )}
          <Button
            size="sm"
            variant="ghost"
            icon="circle-stop"
            className="as-composer-stop"
            disabled={!canStop}
            aria-disabled={stoppingShown || undefined}
            onClick={stop}
          >
            {stoppingShown ? "Stopping…" : "Stop"}
          </Button>
          <Button type="submit" size="sm" variant="primary" icon="arrow-up" disabled={!canSend}>
            {sending ? "Sending…" : "Send"}
          </Button>
        </div>
      </div>
      <span id={hintId} className="as-composer-hint" data-warn={tooLong || undefined}>
        {tooLong
          ? `Too long: ${String(Math.ceil(size / 1024))} KiB of ${String(Math.floor(maxBytes / 1024))} KiB`
          : needsText
            ? "Add a message to send with the image"
            : coarsePointer()
              ? "Send to send, Enter for a new line"
              : "Enter to send, Shift+Enter for a new line"}
      </span>
      {error && (
        <p className="ah-small as-error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
