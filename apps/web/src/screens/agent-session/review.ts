/**
 * Review comments on the changed files: a comment is a message to the session's own Claude,
 * so it is kept in the session's log and answered in the conversation. Its first line anchors
 * it to a file, a change and its lines, in words Claude reads and this page parses back:
 *
 *   Review comment on `src/app.py`, change 2, lines 42-44:
 *
 * then the selected code (a fenced diff), then what you wrote. A reply in the thread starts
 * "Reply to review comment on …" with the same anchor. Claude's answer is its text after the
 * message, up to your next one.
 */
import type { SendingView, TranscriptEntry } from "./model";

/** Which numbers `start`-`end` count: the new file's lines, the old file's (a removal), or the
 * lines of a diff that has no file line numbers. */
export type AnchorSide = "new" | "old" | "diff";

export interface ReviewAnchor {
  path: string;
  /** The change in the file's review, from 1. */
  change: number;
  side: AnchorSide;
  start: number;
  end: number;
}

export interface ReviewMessage {
  key: string;
  author: "you" | "claude";
  text: string;
  /** Still sending (yours) or streaming (Claude's). */
  pending: boolean;
}

export interface ReviewThread {
  /** The first comment's key: stable for the thread's life. */
  key: string;
  anchor: ReviewAnchor;
  messages: ReviewMessage[];
  /** Your last word has no answer from Claude yet. */
  waiting: boolean;
}

const SIDE_WORDS: Record<AnchorSide, string> = {
  new: "lines",
  old: "old lines",
  diff: "diff lines",
};

const HEADER =
  /^(Review comment|Reply to review comment) on `([^`\n]+)`, change (\d+), (lines|old lines|diff lines) (\d+)(?:-(\d+))?:/;

export const anchorKey = (anchor: ReviewAnchor) =>
  `${anchor.path}#${String(anchor.change)}#${anchor.side}${String(anchor.start)}-${String(anchor.end)}`;

function anchorWords(anchor: ReviewAnchor): string {
  const range =
    anchor.start === anchor.end
      ? String(anchor.start)
      : `${String(anchor.start)}-${String(anchor.end)}`;
  return `\`${anchor.path}\`, change ${String(anchor.change)}, ${SIDE_WORDS[anchor.side]} ${range}`;
}

/** A new comment's message: the anchor, the code it is about, then the comment. */
export function commentMessage(anchor: ReviewAnchor, code: string, comment: string): string {
  return `Review comment on ${anchorWords(anchor)}:\n\n\`\`\`diff\n${code}\n\`\`\`\n\n${comment.trim()}`;
}

/** A reply in a thread: the same anchor, then the reply. */
export function replyMessage(anchor: ReviewAnchor, reply: string): string {
  return `Reply to review comment on ${anchorWords(anchor)}:\n\n${reply.trim()}`;
}

/** The anchor of a review message, and what you wrote (without the anchor and the code). */
export function parseReview(
  text: string,
): { anchor: ReviewAnchor; reply: boolean; body: string } | null {
  const match = HEADER.exec(text);
  if (!match) return null;
  const [header, kind = "", path = "", change = "0", words = "", start = "0", end] = match;
  const side: AnchorSide = words === "old lines" ? "old" : words === "diff lines" ? "diff" : "new";
  let rest = text.slice(header.length).replace(/^\s*\n/, "");
  const fence = /^\s*```[^\n]*\n[\s\S]*?\n```[ \t]*(\n|$)/.exec(rest);
  if (fence) rest = rest.slice(fence[0].length);
  return {
    anchor: {
      path,
      change: Number(change),
      side,
      start: Number(start),
      end: Number(end ?? start),
    },
    reply: kind === "Reply to review comment",
    body: rest.trim(),
  };
}

/**
 * The review threads of a session, from its conversation: each comment, the replies to it and
 * Claude's answers (its text after each of them, up to your next message), first commented first.
 * Messages still sending show as pending.
 */
export function reviewThreads(
  entries: readonly TranscriptEntry[],
  sending: readonly SendingView[] = [],
): ReviewThread[] {
  const threads = new Map<string, ReviewThread>();
  let answering: ReviewThread | null = null;
  const add = (key: string, text: string, pending: boolean): ReviewThread | null => {
    const parsed = parseReview(text);
    if (!parsed) return null;
    const id = anchorKey(parsed.anchor);
    let thread = threads.get(id);
    if (!thread) {
      thread = { key, anchor: parsed.anchor, messages: [], waiting: false };
      threads.set(id, thread);
    }
    thread.messages.push({ key, author: "you", text: parsed.body, pending });
    thread.waiting = true;
    return thread;
  };
  for (const entry of entries) {
    if (entry.kind === "user") {
      answering = add(entry.key, entry.text, false);
    } else if (entry.kind === "assistant" && answering && entry.text.trim() !== "") {
      answering.messages.push({
        key: entry.key,
        author: "claude",
        text: entry.text,
        pending: entry.streaming,
      });
      answering.waiting = false;
    }
  }
  for (const send of sending) add(send.key, send.text, true);
  return [...threads.values()];
}
