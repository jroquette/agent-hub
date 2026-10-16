import { describe, expect, it } from "vitest";

import type { TranscriptEntry } from "./model";
import {
  commentMessage,
  parseReview,
  replyMessage,
  reviewThreads,
  type ReviewAnchor,
} from "./review";

const ANCHOR: ReviewAnchor = { path: "/r/src/app.py", change: 2, side: "new", start: 42, end: 44 };

const user = (seq: number, text: string): TranscriptEntry => ({
  kind: "user",
  key: `u-${String(seq)}`,
  seq,
  at: "2026-10-16T10:00:00Z",
  text,
  redacted: false,
  queued: false,
  screenshot: false,
  screenshotCount: 0,
});
const claude = (seq: number, text: string, streaming = false): TranscriptEntry => ({
  kind: "assistant",
  key: `a-${String(seq)}`,
  seq,
  at: streaming ? null : "2026-10-16T10:00:01Z",
  block: 0,
  text,
  streaming,
  lastDelta: -1,
  redacted: false,
});

describe("review (comments)", () => {
  it("writes a comment Claude can read and this page parses back", () => {
    const text = commentMessage(ANCHOR, "-a\n+b", "  Why b?  ");

    expect(text).toBe(
      "Review comment on `/r/src/app.py`, change 2, lines 42-44:\n\n```diff\n-a\n+b\n```\n\nWhy b?",
    );
    expect(parseReview(text)).toEqual({ anchor: ANCHOR, reply: false, body: "Why b?" });
  });

  it("parses a reply, one line, an old side and a diff without line numbers", () => {
    expect(parseReview(replyMessage(ANCHOR, "Thanks."))).toEqual({
      anchor: ANCHOR,
      reply: true,
      body: "Thanks.",
    });
    const old = { ...ANCHOR, side: "old" as const, start: 7, end: 7 };
    expect(parseReview(commentMessage(old, "-x", "Gone?"))?.anchor).toEqual(old);
    const diff = { ...ANCHOR, side: "diff" as const, start: 3, end: 5 };
    expect(parseReview(commentMessage(diff, " y", "Hm"))?.anchor).toEqual(diff);
    expect(parseReview("Just a message")).toBeNull();
  });

  it("threads a comment with Claude's answers and your replies, until your next message", () => {
    const threads = reviewThreads([
      user(1, "Start."),
      claude(2, "Done."),
      user(3, commentMessage(ANCHOR, "+b", "Why b?")),
      claude(4, "Because b is right."),
      user(5, "Unrelated question"),
      claude(6, "Unrelated answer"),
      user(7, replyMessage(ANCHOR, "Use c instead.")),
      claude(8, "Switching to c", true),
    ]);

    expect(threads).toHaveLength(1);
    expect(threads[0]?.key).toBe("u-3");
    expect(threads[0]?.messages.map((m) => [m.author, m.text, m.pending])).toEqual([
      ["you", "Why b?", false],
      ["claude", "Because b is right.", false],
      ["you", "Use c instead.", false],
      ["claude", "Switching to c", true],
    ]);
    expect(threads[0]?.waiting).toBe(false);
  });

  it("waits for Claude after your comment, and shows one still sending", () => {
    const threads = reviewThreads(
      [user(1, commentMessage(ANCHOR, "+b", "Why b?"))],
      [{ key: "send-1", text: replyMessage(ANCHOR, "Any news?"), seq: null }],
    );

    expect(threads[0]?.waiting).toBe(true);
    expect(threads[0]?.messages.at(-1)).toEqual({
      key: "send-1",
      author: "you",
      text: "Any news?",
      pending: true,
    });
  });
});
