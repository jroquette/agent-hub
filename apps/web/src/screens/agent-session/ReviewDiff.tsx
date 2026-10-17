import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";

import { Button, Icon, Markdown } from "../../components";
import { ApiProblem } from "../../lib/api";
import { cx } from "../../lib/cx";
import { readStored, writeStored } from "../../lib/storage";
import { diffLines, type DiffLine } from "./ToolCallCard";
import {
  commentMessage,
  parseReview,
  replyMessage,
  type AnchorSide,
  type ReviewAnchor,
  type ReviewThread,
} from "./review";

export const resolvedKey = (sessionId: string) => `ah.chat.resolved.${sessionId}`;

/** The threads you resolved (by thread key), kept in this browser per session. */
export function useResolvedThreads(sessionId: string) {
  const [resolved, setResolved] = useState<ReadonlySet<string>>(() => {
    try {
      const value: unknown = JSON.parse(readStored(resolvedKey(sessionId)) ?? "[]");
      return new Set(Array.isArray(value) ? value.filter((v) => typeof v === "string") : []);
    } catch {
      return new Set();
    }
  });
  const toggle = useCallback(
    (key: string) => {
      setResolved((before) => {
        const next = new Set(before);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        writeStored(resolvedKey(sessionId), JSON.stringify([...next]));
        return next;
      });
    },
    [sessionId],
  );
  return { resolved, toggle };
}

export interface ResolvedThreads {
  resolved: ReadonlySet<string>;
  toggle: (key: string) => void;
}

/** What the review drawer's diffs comment with: the session's threads, the resolved ones, and
 * how a comment reaches Claude (absent: the diffs are read-only). */
export interface ReviewComments {
  threads: readonly ReviewThread[];
  resolved: ResolvedThreads;
  onComment?: ((text: string) => Promise<unknown> | undefined) | undefined;
}

export const ReviewCommentsContext = createContext<ReviewComments | null>(null);

/** A row's place in the file (or in the diff), when it can be commented on. */
interface LineRef {
  side: AnchorSide;
  n: number;
}

function refOf(line: DiffLine, index: number, numbered: boolean): LineRef | null {
  if (line.kind === "hunk" || line.kind === "head") return null;
  if (!numbered) return { side: "diff", n: index + 1 };
  if (line.kind === "del") return line.oldNo === null ? null : { side: "old", n: line.oldNo };
  return line.newNo === null ? null : { side: "new", n: line.newNo };
}

/** The anchor of the selected rows: the new file's lines when any is there, else the old's. */
function anchorOf(refs: readonly LineRef[], path: string, change: number): ReviewAnchor | null {
  const side: AnchorSide = refs.some((r) => r.side === "new")
    ? "new"
    : refs.some((r) => r.side === "old")
      ? "old"
      : "diff";
  const numbers = refs.filter((r) => r.side === side).map((r) => r.n);
  if (numbers.length === 0) return null;
  return { path, change, side, start: Math.min(...numbers), end: Math.max(...numbers) };
}

function linesLabel(anchor: ReviewAnchor): string {
  const words = anchor.side === "old" ? "Old line" : anchor.side === "diff" ? "Diff line" : "Line";
  return anchor.start === anchor.end
    ? `${words} ${String(anchor.start)}`
    : `${words}s ${String(anchor.start)}–${String(anchor.end)}`;
}

function problemText(error: unknown): string {
  if (error instanceof ApiProblem)
    return error.detail ? `${error.title}: ${error.detail}` : error.title;
  return "Could not send it. Try again.";
}

/** A text box that posts with Cmd/Ctrl+Enter or its button; Esc cancels. */
function CommentBox({
  label,
  submitLabel,
  placeholder,
  onSubmit,
  onCancel,
  focusOnOpen = false,
}: {
  label: string;
  submitLabel: string;
  placeholder: string;
  onSubmit: (text: string) => Promise<unknown> | undefined;
  onCancel?: (() => void) | undefined;
  focusOnOpen?: boolean;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  // A box opened on purpose (a + pressed, Reply…) takes the keyboard at once.
  useEffect(() => {
    if (focusOnOpen) box.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [error, setError] = useState<string | null>(null);
  const submit = () => {
    if (busy || text.trim() === "") return;
    setBusy(true);
    setError(null);
    void Promise.resolve()
      .then(() => onSubmit(text))
      .then(
        () => {
          setText("");
        },
        (cause: unknown) => {
          setError(problemText(cause));
        },
      )
      .finally(() => {
        setBusy(false);
      });
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      submit();
    } else if (event.key === "Escape" && onCancel) {
      event.preventDefault();
      event.stopPropagation();
      onCancel();
    }
  };
  return (
    <div className="as-comment-box">
      <textarea
        className="ah-input"
        aria-label={label}
        placeholder={placeholder}
        rows={3}
        value={text}
        disabled={busy}
        ref={box}
        onChange={(event) => {
          setText(event.target.value);
        }}
        onKeyDown={onKeyDown}
      />
      <div className="as-comment-box-bar">
        <span className="ah-small ah-subtle">⌘/Ctrl+Enter to send to Claude</span>
        <span className="ah-grow" />
        {onCancel && (
          <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        )}
        <Button
          size="sm"
          variant="primary"
          icon="message-square"
          disabled={busy || text.trim() === ""}
          onClick={submit}
        >
          {busy ? "Sending…" : submitLabel}
        </Button>
      </div>
      {error && (
        <p className="ah-small as-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

/** One review thread: your comment and replies, Claude's answers, a reply box, Resolve. */
function Thread({
  thread,
  resolved,
  onReply,
}: {
  thread: ReviewThread;
  resolved: ResolvedThreads;
  onReply: ((text: string) => Promise<unknown> | undefined) | undefined;
}) {
  const closed = resolved.resolved.has(thread.key);
  const [replying, setReplying] = useState(false);
  const [shown, setShown] = useState(false);
  const label = linesLabel(thread.anchor);
  const head = (
    <header className="as-thread-head">
      <Icon name={closed ? "check-check" : "message-square"} size="sm" />
      <span>{label}</span>
      <span className="ah-small ah-muted">
        · {thread.messages.length} {thread.messages.length === 1 ? "message" : "messages"}
      </span>
      {thread.waiting && !closed && (
        <span className="as-thread-waiting">
          <Icon name="loader" size="sm" className="as-spin" />
          Waiting for Claude
        </span>
      )}
      <span className="ah-grow" />
      {closed && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setShown((value) => !value);
          }}
        >
          {shown ? "Hide" : "Show"}
        </Button>
      )}
      <Button
        size="sm"
        variant="ghost"
        icon={closed ? "rotate-ccw" : "check"}
        onClick={() => {
          resolved.toggle(thread.key);
          setShown(false);
        }}
      >
        {closed ? "Reopen" : "Resolve"}
      </Button>
    </header>
  );
  return (
    <section
      className={cx("as-thread", closed && "as-thread-resolved")}
      aria-label={`Review thread on ${label}`}
    >
      {head}
      {(!closed || shown) && (
        <>
          <ol className="as-thread-messages">
            {thread.messages.map((message) => (
              <li
                key={message.key}
                className={cx(
                  "as-thread-message",
                  `as-thread-${message.author}`,
                  message.pending && "as-thread-pending",
                )}
              >
                <span className="as-thread-author">
                  {message.author === "you" ? "You" : "Claude"}
                  {message.pending && (message.author === "you" ? " · sending…" : " · writing…")}
                </span>
                {message.author === "claude" ? (
                  <Markdown source={message.text} />
                ) : (
                  <p className="as-thread-text">{message.text}</p>
                )}
              </li>
            ))}
          </ol>
          {onReply &&
            !closed &&
            (replying ? (
              <CommentBox
                label={`Reply on ${label}`}
                submitLabel="Reply"
                placeholder="Reply to Claude…"
                focusOnOpen
                onSubmit={async (text) => {
                  await onReply(replyMessage(thread.anchor, text));
                  setReplying(false);
                }}
                onCancel={() => {
                  setReplying(false);
                }}
              />
            ) : (
              <button
                type="button"
                className="as-thread-reply"
                onClick={() => {
                  setReplying(true);
                }}
              >
                Reply…
              </button>
            ))}
        </>
      )}
    </section>
  );
}

export interface ReviewDiffProps {
  diff: string;
  label: string;
  /** The diff carries the file's line numbers (git's two gutters show). */
  numbered: boolean;
  /** The file's path, as Claude knows it. */
  path: string;
  /** The change in the file's review, from 1. */
  change: number;
  /** The threads on this change. */
  threads: readonly ReviewThread[];
  resolved: ResolvedThreads;
  /** Sends a comment or a reply to the session's Claude; without it the threads are read-only. */
  onComment?: ((text: string) => Promise<unknown> | undefined) | undefined;
}

/**
 * A change's diff you can comment on, like a pull request's: press + beside a line (Shift+click
 * another to take the lines between), write, and the comment goes to the session's Claude with
 * the code it is about. Each thread shows under its last line; one whose lines left the diff
 * shows at its end.
 */
export function ReviewDiff({
  diff,
  label,
  numbered,
  path,
  change,
  threads,
  resolved,
  onComment,
}: ReviewDiffProps) {
  const rows = diffLines(diff).filter((line) => line.kind !== "head");
  const refs = rows.map((line, i) => refOf(line, i, numbered));
  const [selection, setSelection] = useState<{ from: number; to: number } | null>(null);
  const low = selection ? Math.min(selection.from, selection.to) : -1;
  const high = selection ? Math.max(selection.from, selection.to) : -1;

  const select = (index: number, event: MouseEvent<HTMLButtonElement>) => {
    setSelection((before) =>
      event.shiftKey && before ? { from: before.from, to: index } : { from: index, to: index },
    );
  };

  const selectedRefs = refs.slice(low, high + 1).filter((ref): ref is LineRef => ref !== null);
  const anchor = selection ? anchorOf(selectedRefs, path, change) : null;
  const code = rows
    .slice(low, high + 1)
    .map((line) => line.text)
    .join("\n");

  const placed = new Map<number, ReviewThread[]>();
  const outdated: ReviewThread[] = [];
  for (const thread of threads) {
    const at = refs.findIndex(
      (ref) => ref?.side === thread.anchor.side && ref.n === thread.anchor.end,
    );
    if (at < 0) outdated.push(thread);
    else placed.set(at, [...(placed.get(at) ?? []), thread]);
  }
  const threadsAt = (list: readonly ReviewThread[] | undefined): ReactNode =>
    list?.map((thread) => (
      <Thread key={thread.key} thread={thread} resolved={resolved} onReply={onComment} />
    ));

  return (
    <div
      className={cx("as-diff as-review-diff", numbered && "as-diff-numbered")}
      // A diff can scroll sideways, so the keyboard must reach it.
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      role="group"
      aria-label={label}
    >
      {rows.map((line, i) => {
        const ref = refs[i];
        const selected = i >= low && i <= high;
        return (
          <div key={i} className="as-review-row">
            <div
              className={cx("as-diff-line", `as-diff-${line.kind}`, selected && "as-diff-selected")}
            >
              {numbered ? (
                <>
                  <span className="as-diff-no" aria-hidden="true">
                    {line.oldNo ?? ""}
                  </span>
                  <span className="as-diff-no" aria-hidden="true">
                    {line.newNo ?? ""}
                  </span>
                </>
              ) : (
                <span className="as-diff-no as-diff-no-single" aria-hidden="true">
                  {ref?.n ?? ""}
                </span>
              )}
              <span className="as-diff-code">
                {onComment && ref && (
                  <button
                    type="button"
                    className="as-diff-add-comment"
                    aria-label={`Comment on ${ref.side === "old" ? "old line" : ref.side === "diff" ? "diff line" : "line"} ${String(ref.n)}`}
                    title="Comment (Shift+click another line to take the lines between)"
                    onClick={(event) => {
                      select(i, event);
                    }}
                  >
                    <Icon name="plus" size="sm" />
                  </button>
                )}
                {line.text}
              </span>
            </div>
            {threadsAt(placed.get(i))}
            {onComment && anchor && i === high && (
              <div className="as-review-compose">
                <p className="ah-small ah-muted as-review-compose-head">
                  <Icon name="message-square" size="sm" /> Comment on {linesLabel(anchor)} for
                  Claude
                </p>
                <CommentBox
                  label={`Comment on ${linesLabel(anchor)}`}
                  submitLabel="Comment"
                  placeholder="Ask Claude about this code, or ask for a change…"
                  focusOnOpen
                  onSubmit={async (text) => {
                    await onComment(commentMessage(anchor, code, text));
                    setSelection(null);
                  }}
                  onCancel={() => {
                    setSelection(null);
                  }}
                />
              </div>
            )}
          </div>
        );
      })}
      {outdated.length > 0 && (
        <div className="as-review-outdated">
          <p className="ah-small ah-muted">On lines this change no longer shows</p>
          {threadsAt(outdated)}
        </div>
      )}
    </div>
  );
}

/** Opens the Changed files drawer on a file: a review comment in the chat links back to it. */
export const OpenReviewFileContext = createContext<((path: string) => void) | null>(null);

/**
 * A review comment or reply in the conversation, read as one: the file and lines it is on, the
 * code it quotes (folded), what you wrote, and a way back to it in the review. Null for any other
 * message.
 */
export function ReviewBubble({ text }: { text: string }) {
  const openFile = useContext(OpenReviewFileContext);
  const parsed = parseReview(text);
  if (!parsed) return null;
  const { anchor, reply, body } = parsed;
  const name = anchor.path.slice(anchor.path.lastIndexOf("/") + 1);
  const code = /```[^\n]*\n([\s\S]*?)\n```/.exec(text)?.[1];
  return (
    <div className="as-bubble as-review-bubble">
      <div className="as-review-bubble-head">
        <Icon name="message-square" size="sm" />
        <span>
          {reply ? "Reply on" : "Review comment on"} <b className="ah-mono">{name}</b> ·{" "}
          {linesLabel(anchor).toLowerCase()}
        </span>
        {openFile && (
          <button
            type="button"
            className="as-review-bubble-open"
            title={anchor.path}
            onClick={() => {
              openFile(anchor.path);
            }}
          >
            Open in review
          </button>
        )}
      </div>
      {code !== undefined && (
        <details className="as-review-bubble-code">
          <summary>Code</summary>
          <pre>{code}</pre>
        </details>
      )}
      <p className="as-review-bubble-body">{body}</p>
    </div>
  );
}
